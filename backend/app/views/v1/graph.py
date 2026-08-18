import logging
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
import openai

from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.db.mongodb import get_db
from app.models.user import UserInDB
from app.views.schemas.graph import GraphNodeResponse, GraphEdgeResponse, NodeDetailResponse
from app.controllers import graph_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])


def _is_markdown_path(file_path: Optional[str]) -> bool:
    if not file_path:
        return False
    lowered = file_path.lower()
    return lowered.endswith((".md", ".markdown"))


def _load_vault_markdown(doc: Optional[dict]) -> Optional[str]:
    if not doc:
        return None

    wiki_rel_path = doc.get("vault_wiki_path")
    if not wiki_rel_path:
        return None

    try:
        from app.controllers.vault_manager import resolve_vault_dir

        vault_dir = resolve_vault_dir(get_settings().VAULT_PATH)
        wiki_file = (vault_dir / wiki_rel_path).resolve()
        if wiki_file.is_file():
            return wiki_file.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Failed to read vault wiki file %s: %s", wiki_rel_path, exc)

    return None


@router.get("/nodes", response_model=List[GraphNodeResponse])
async def list_nodes(
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
    repo_name: Optional[str] = Query(None, description="Filter nodes by repository"),
    node_type: Optional[str] = Query(None, description="Filter nodes by type (Repository, File, Function, Class, Concept, Section, DesignSystem)"),
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    List graph nodes with optional filtering by repo and type.
    """
    EXCLUDED_FROM_DEFAULT_VIEW = {"DesignSystem"}

    if node_type:
        nodes = await graph_store.get_nodes_by_type(db, node_type, limit=limit)
    else:
        # Use get_all_nodes (find({})) and filter in Python — $nin is unreliable
        # with this Motor version when a sparse index exists on the type field.
        nodes_all = await graph_store.get_all_nodes(db, skip=skip, limit=limit)
        nodes = [n for n in nodes_all if n.get("type") not in EXCLUDED_FROM_DEFAULT_VIEW]

    # Manual filtering for repo_name since helper is flat
    if repo_name:
        nodes = [n for n in nodes if n.get("repo_name") == repo_name]

    result = []
    for n in nodes:
        result.append(GraphNodeResponse(
            id=n["id"],
            type=n["type"],
            name=n["name"],
            repo_name=n.get("repo_name"),
            file_path=n.get("file_path"),
            language=n.get("language"),
            summary=n.get("summary"),
            metadata=n.get("metadata", {}),
        ))
    return result


@router.get("/edges", response_model=List[GraphEdgeResponse])
async def list_edges(
    skip: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=2000),
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    List all relationship edges in the knowledge graph.
    """
    edges = await graph_store.get_all_edges(db, skip=skip, limit=limit)
    result = []
    for e in edges:
        result.append(GraphEdgeResponse(
            id=e["id"],
            from_id=e["from_id"],
            to_id=e["to_id"],
            type=e["type"],
            weight=e.get("weight"),
        ))
    return result


@router.get("/nodes/{node_id:path}", response_model=NodeDetailResponse)
async def get_node_details(
    node_id: str,
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Get detailed information about a single graph node, including its neighbors and edges.
    """
    node = await graph_store.get_node(db, node_id)
    if not node:
        # Fallback 1: Try query by file_path matching exactly or with path slash swap
        normalized_path = node_id.replace("\\", "/")
        alt_path = node_id.replace("/", "\\")

        node_doc = await db.graph_nodes.find_one({
            "$or": [
                {"file_path": node_id},
                {"file_path": normalized_path},
                {"file_path": alt_path},
                {"file_path": f"wiki/{node_id}"},
                {"file_path": f"wiki/{normalized_path}"},
            ]
        })

        # Fallback 2: Try query by name (e.g. Concept name or Repository name)
        if not node_doc:
            node_doc = await db.graph_nodes.find_one({"name": node_id})

        # Fallback 3: Try matching suffix of file_path
        if not node_doc:
            import re
            base_name = normalized_path
            if base_name.endswith(".md"):
                base_name = base_name[:-3]
            pattern = f"{re.escape(base_name)}(\\.[a-zA-Z0-9]+)?$"
            node_doc = await db.graph_nodes.find_one({
                "file_path": {"$regex": pattern, "$options": "i"}
            })

        if node_doc:
            node = dict(node_doc)
            node["id"] = node.pop("_id")

    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Graph node not found",
        )

    # Fetch content for the node depending on its type
    content = None
    n_type = node.get("type", "")

    # Try to find a matching document to load document_chunks content (for wiki/doc nodes)
    doc = None
    file_path = node.get("file_path")
    current_node_id = node.get("id")
    if file_path:
        normalized_path = file_path.replace("\\", "/")
        doc = await db.documents.find_one({
            "$or": [
                {"vault_wiki_path": normalized_path},
                {"vault_wiki_path": file_path}
            ]
        })
    if not doc and current_node_id:
        doc = await db.documents.find_one({"_id": current_node_id})
    if not doc and node.get("repo_name") and file_path:
        doc = await db.documents.find_one({
            "repo_name": node.get("repo_name"),
            "$or": [
                {"original_filename": file_path},
                {"original_filename": file_path.replace("/", "\\")},
                {"original_filename": file_path.replace("\\", "/")}
            ]
        })

    # Special case: wiki index node — generate content dynamically from DB
    # so Repository Overviews always reflects live ingested repos (static file is often stale)
    is_wiki_index = (
        node.get("file_path") in ("index.md", "wiki/index.md")
        or node.get("id") == "wiki_index"
    )

    if is_wiki_index:
        repo_nodes = await db.graph_nodes.find({"type": "Repository"}).sort("name", 1).to_list(length=200)
        doc_nodes = await db.documents.find(
            {"ingestion_status": "done"},
            {"title": 1, "original_filename": 1, "_id": 1, "repo_name": 1}
        ).sort("title", 1).to_list(length=200)

        repo_lines = []
        for r in repo_nodes:
            r_id = str(r["_id"])
            r_name = r.get("name", r_id)
            repo_lines.append(f"- [{r_name}](/wiki/{r_id})")

        doc_lines = []
        seen_repo_names = {r.get("repo_name") for r in repo_nodes}
        for d in doc_nodes:
            if d.get("repo_name") in seen_repo_names:
                continue
            d_id = str(d["_id"])
            d_title = d.get("title") or d.get("original_filename") or d_id
            doc_lines.append(f"- [{d_title}](/wiki/{d_id})")

        lines = ["# Wiki Index", "", "## Repository Overviews"]
        lines.extend(repo_lines if repo_lines else ["- None yet"])
        lines += ["", "## Documents"]
        lines.extend(doc_lines if doc_lines else ["- None yet"])
        lines += ["", "## System Files", "- [log](log.md)"]
        content = "\n".join(lines)
        node["language"] = "markdown"
    elif doc:
        content = _load_vault_markdown(doc)
        node["language"] = "markdown" if _is_markdown_path(doc.get("vault_wiki_path")) or doc.get("file_type") == "md" else node.get("language")
        if not content:
            chunks_cursor = db.document_chunks.find(
                {"document_id": doc["_id"]}
            ).sort([("page_number", 1), ("_id", 1)])
            chunks = await chunks_cursor.to_list(length=None)
            if chunks:
                content = "\n\n".join(c["content"] for c in chunks)
    elif n_type == "Repository":
        # 1. Search in code_chunks
        readme_chunk = await db.code_chunks.find_one({
            "repo_name": node.get("repo_name"),
            "file_path": {"$regex": "(^|/)readme(\\.[a-zA-Z0-9]+)?$", "$options": "i"}
        })
        if readme_chunk:
            chunks_cursor = db.code_chunks.find({
                "repo_name": node.get("repo_name"),
                "file_path": readme_chunk["file_path"]
            }).sort("line_start", 1)
            chunks = await chunks_cursor.to_list(length=None)
            if chunks:
                content = "\n\n".join(c["content"] for c in chunks)
                node["language"] = "markdown" if readme_chunk["file_path"].lower().endswith((".md", ".markdown")) else "text"
        else:
            # 2. Search in documents (for vault repos)
            readme_doc = await db.documents.find_one({
                "repo_name": node.get("repo_name"),
                "original_filename": {"$regex": "(^|/)readme(\\.[a-zA-Z0-9]+)?$", "$options": "i"}
            })
            if readme_doc:
                content = _load_vault_markdown(readme_doc)
                if content:
                    node["language"] = "markdown"
                else:
                    chunks_cursor = db.document_chunks.find(
                        {"document_id": readme_doc["_id"]}
                    ).sort([("page_number", 1), ("_id", 1)])
                    chunks = await chunks_cursor.to_list(length=None)
                    if chunks:
                        content = "\n\n".join(c["content"] for c in chunks)
                        node["language"] = "markdown" if readme_doc["original_filename"].lower().endswith((".md", ".markdown")) else "text"
    elif n_type == "File":
        chunks_cursor = db.code_chunks.find(
            {"repo_name": node.get("repo_name"), "file_path": node.get("file_path")}
        ).sort("line_start", 1)
        chunks = await chunks_cursor.to_list(length=None)
        if chunks:
            content = "\n\n".join(c["content"] for c in chunks)
    elif n_type == "Document":
        chunks_cursor = db.document_chunks.find(
            {"document_id": node.get("id")}
        ).sort([("page_number", 1), ("_id", 1)])
        chunks = await chunks_cursor.to_list(length=None)
        if chunks:
            content = "\n\n".join(c["content"] for c in chunks)
    elif n_type == "Section":
        chunk = await db.document_chunks.find_one({"_id": node.get("id")})
        if chunk:
            content = chunk.get("content")
    elif n_type == "Project":
        incoming_edges = await db.graph_edges.find({
            "to_id": current_node_id,
            "type": "REFERENCES"
        }).to_list(length=100)
        from_ids = [e["from_id"] for e in incoming_edges]
        docs_cursor = db.graph_nodes.find({
            "_id": {"$in": from_ids},
            "type": "Document"
        })
        related_docs = await docs_cursor.to_list(length=100)
        if related_docs:
            lines = [f"# Project: {node.get('name')}", "\n### Uploaded Documents in this Project\n"]
            for d in related_docs:
                lines.append(f"- [{d['name']}](/wiki/{d['_id']})")
            content = "\n".join(lines)
        else:
            content = f"# Project: {node.get('name')}\n\nNo documents have been uploaded for this project yet."
        node["language"] = "markdown"
    elif n_type == "Concept":
        content = node.get("content")
        if not content:
            settings = get_settings()
            if settings.OPENAI_API_KEY:
                try:
                    incoming_edges = await db.graph_edges.find({
                        "to_id": current_node_id,
                        "type": "REFERENCES"
                    }).to_list(length=50)

                    from_ids = [e["from_id"] for e in incoming_edges]

                    code_chunks = await db.code_chunks.find({
                        "_id": {"$in": from_ids}
                    }).to_list(length=15)

                    doc_chunks = await db.document_chunks.find({
                        "_id": {"$in": from_ids}
                    }).to_list(length=15)

                    contexts = []
                    for c in code_chunks:
                        contexts.append(f"--- File: {c.get('file_path', 'unknown')} ---\n{c.get('content', '')}")
                    for c in doc_chunks:
                        contexts.append(f"--- Section (Doc ID: {c.get('document_id', 'unknown')}) ---\n{c.get('content', '')}")

                    context_str = "\n\n".join(contexts)

                    if settings.OPENAI_ENDPOINT and "azure" in settings.OPENAI_ENDPOINT.lower():
                        client_ai = openai.AsyncAzureOpenAI(
                            api_key=settings.OPENAI_API_KEY,
                            azure_endpoint=settings.OPENAI_ENDPOINT,
                            api_version=settings.OPENAI_API_VERSION or "2024-08-01-preview",
                        )
                    else:
                        client_ai = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

                    prompt = (
                        f"You are a technical analyst. Write a comprehensive, premium Markdown page explaining the concept: '{node.get('name')}' based ONLY on the provided repository context.\n\n"
                        f"Analyze the following code and text context blocks where it is referenced:\n\n{context_str}\n\n"
                        f"CRITICAL REQUIREMENTS:\n"
                        f"- Ground the explanation, examples, and code snippets strictly in the provided context blocks. Do NOT include general explanations, tutorials, or external library examples (like Iris dataset or generic library tutorials) if they are not in the context.\n"
                        f"- Do not reference any classes, functions, variable names, APIs, databases, or libraries that do not appear in the context.\n"
                        f"- Detail the 'Usage in the Repository' section by explaining the specific files and implementation visible in the context where '{node.get('name')}' is implemented or configured.\n"
                        f"- Start the markdown directly with '# {node.get('name')}'."
                    )

                    resp = await client_ai.chat.completions.create(
                        model=settings.OPENAI_CHAT_MODEL or "gpt-4o",
                        messages=[
                            {"role": "system", "content": "You are a professional documentation writer."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.2
                    )
                    content = resp.choices[0].message.content.strip()

                    summary_prompt = f"Summarize how the concept '{node.get('name')}' is used in the codebase in one concise sentence based on this content:\n\n{content}"
                    resp_sum = await client_ai.chat.completions.create(
                        model=settings.OPENAI_CHAT_MODEL or "gpt-4o",
                        messages=[
                            {"role": "system", "content": "You are a concise summarizer. Respond with only one sentence."},
                            {"role": "user", "content": summary_prompt}
                        ],
                        temperature=0.2
                    )
                    summary = resp_sum.choices[0].message.content.strip()

                    await db.graph_nodes.update_one(
                        {"_id": current_node_id},
                        {"$set": {"content": content, "summary": summary}}
                    )
                    node["summary"] = summary
                except Exception as exc:
                    logger.error(f"Error generating Concept page for {current_node_id}: {exc}")
                    content = f"# {node.get('name')}\n\nFailed to generate concept description: {exc}"
            else:
                content = f"# {node.get('name')}\n\nThis concept is mentioned in the repository, but automatic concept summarization is disabled (OpenAI key not configured)."
    elif n_type == "DesignSystem":
        from app.controllers.vault_manager import resolve_vault_dir, repo_slug
        try:
            vault_dir = resolve_vault_dir(get_settings().VAULT_PATH)
            slug = repo_slug(node.get("repo_name") or "")
            design_file = vault_dir / "wiki" / "repositories" / slug / "design.md"
            if design_file.is_file():
                content = design_file.read_text(encoding="utf-8", errors="replace")
                node["language"] = "markdown"
            else:
                logger.warning("Design system file not found: %s", design_file)
        except Exception as exc:
            logger.warning("Failed to read DesignSystem markdown file: %s", exc)

    # Fetch neighbors (depth = 1)
    neighbors_raw = await graph_store.get_neighbors(db, current_node_id, depth=1)
    neighbors = []
    for n in neighbors_raw:
        neighbors.append(GraphNodeResponse(
            id=n["id"],
            type=n["type"],
            name=n["name"],
            repo_name=n.get("repo_name"),
            file_path=n.get("file_path"),
            language=n.get("language"),
            summary=n.get("summary"),
            metadata=n.get("metadata", {}),
        ))

    # Fetch incident edges
    edges_raw = await graph_store.get_edges_from(db, current_node_id)
    edges = []
    for e in edges_raw:
        edges.append(GraphEdgeResponse(
            id=e["id"],
            from_id=e["from_id"],
            to_id=e["to_id"],
            type=e["type"],
            weight=e.get("weight"),
        ))

    node_resp = GraphNodeResponse(
        id=node["id"],
        type=node["type"],
        name=node["name"],
        repo_name=node.get("repo_name"),
        file_path=node.get("file_path"),
        language=node.get("language"),
        summary=node.get("summary"),
        content=content,
        metadata=node.get("metadata", {}),
    )

    return NodeDetailResponse(
        node=node_resp,
        neighbors=neighbors,
        edges=edges,
    )
