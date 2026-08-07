import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import numpy as np
import openai

from app.core.config import get_settings
from app.controllers.ingestion.parsers.base_parser import ParsedChunk

logger = logging.getLogger(__name__)

CONCEPT_EXTRACTION_PROMPT = """You are a code and document analyst. Extract structured knowledge from the given code or text.
Extract only repository-based concepts that are directly implemented, configured, or explicitly discussed in the provided code or text. Do not extract general, generic, or broad concepts (e.g., do not extract generic library names or general design patterns unless the code contains a specific, custom implementation of them). Every concept must be concrete and directly visible in the provided code/text.
Return a JSON object with these fields:
{
  "concepts": ["list of repository-specific concepts directly implemented or discussed in the code/text"],
  "technologies": ["specific libraries, frameworks, or tools used"],
  "one_line_summary": "one sentence describing what this code/text does"
}
Return ONLY the JSON. No explanation, no markdown fences."""


def _get_openai_client():
    settings = get_settings()
    if settings.OPENAI_ENDPOINT and "azure" in settings.OPENAI_ENDPOINT.lower():
        return openai.AsyncAzureOpenAI(
            api_key=settings.OPENAI_API_KEY,
            azure_endpoint=settings.OPENAI_ENDPOINT,
            api_version=settings.OPENAI_API_VERSION or "2024-08-01-preview",
        )
    return openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def _node_id(node_type: str, content: str) -> str:
    h = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"{node_type}_{h}"


async def build_graph_from_repo(
    repo_name: str,
    repo_dir: str,
    db
) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    nodes_created = 0
    edges_created = 0

    # Step 1 — Run Graphify on the cloned repo directory
    import sys
    sys_dir = os.path.dirname(sys.executable)
    graphify_bin = os.path.join(sys_dir, "graphify.exe" if os.name == "nt" else "graphify")
    if not os.path.exists(graphify_bin):
        graphify_bin = "graphify"

    settings = get_settings()
    env = {**os.environ}
    if settings.OPENAI_API_KEY:
        env["AZURE_OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    if settings.OPENAI_ENDPOINT:
        env["AZURE_OPENAI_ENDPOINT"] = settings.OPENAI_ENDPOINT
    if settings.OPENAI_API_VERSION:
        env["AZURE_OPENAI_API_VERSION"] = settings.OPENAI_API_VERSION
    if settings.OPENAI_CHAT_MODEL:
        env["AZURE_OPENAI_DEPLOYMENT"] = settings.OPENAI_CHAT_MODEL
        env["GRAPHIFY_AZURE_MODEL"] = settings.OPENAI_CHAT_MODEL

    import subprocess
    def run_graphify():
        return subprocess.run(
            [graphify_bin, "extract", repo_dir, "--backend", "azure", "--out", repo_dir],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    graphify_nodes = []
    graphify_edges = []

    try:
        res = await asyncio.to_thread(run_graphify)
        if res.returncode != 0:
            logger.warning(f"Graphify extract failed for {repo_name}: {res.stderr.decode(errors='ignore')}")
        else:
            # Step 2 — Read and parse graph.json
            graph_path = os.path.join(repo_dir, "graphify-out", "graph.json")
            if not os.path.exists(graph_path):
                graph_path = os.path.join(repo_dir, "graph.json")

            if os.path.exists(graph_path):
                try:
                    with open(graph_path, "r", encoding="utf-8", errors="ignore") as f:
                        graph_data = json.load(f)
                        graphify_nodes = graph_data.get("nodes", [])
                        graphify_edges = graph_data.get("edges", [])
                except Exception as exc:
                    logger.warning(f"Failed to read graph.json: {exc}")
            else:
                logger.warning("graph.json not found in %s after graphify extract", repo_dir)
    except Exception as exc:
        logger.warning(f"Graphify execution failed for {repo_name}: {exc}")

    # Step 3 — Map Graphify nodes → MongoDB graph_nodes
    lookup = {}
    for node in graphify_nodes:
        file_path = node.get("source_file") or node.get("file") or ""
        name = node.get("label") or node.get("name") or ""
        g_type = node.get("file_type") or node.get("type") or ""

        # Type mapping
        g_type_lower = g_type.lower()
        if g_type_lower in ("function", "method"):
            n_type = "Function"
        elif g_type_lower == "class":
            n_type = "Class"
        elif g_type_lower in ("file", "module"):
            n_type = "File"
        elif g_type_lower in ("concept", "theme", "community"):
            n_type = "Concept"
        else:
            n_type = g_type.capitalize() if g_type else "Other"

        id_str = f"{repo_name}:{file_path}:{name}:{g_type}"
        mongo_id = hashlib.sha256(id_str.encode()).hexdigest()[:24]

        # Infer language
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        ext_map = {
            "py": "python",
            "js": "javascript",
            "jsx": "javascript",
            "ts": "typescript",
            "tsx": "typescript",
            "html": "html",
            "css": "css",
            "java": "java",
            "cpp": "cpp",
            "c": "c",
            "h": "c",
            "go": "go",
            "sh": "shell",
            "sql": "sql",
            "md": "markdown",
            "txt": "text",
            "json": "json",
        }
        language = ext_map.get(ext, "text")

        # Upsert
        await db.graph_nodes.update_one(
            {"_id": mongo_id},
            {"$set": {
                "type": n_type,
                "name": name,
                "repo_name": repo_name,
                "file_path": file_path,
                "language": language,
                "summary": node.get("summary"),
                "metadata": {
                    "graphify_id": node.get("id"),
                    "graphify_type": g_type,
                },
                "updated_at": now,
            }, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        nodes_created += 1
        lookup[node["id"]] = mongo_id

    # Step 4 — Map Graphify edges → MongoDB graph_edges
    for edge in graphify_edges:
        source_id = edge.get("source")
        target_id = edge.get("target")

        from_mongo_id = lookup.get(source_id)
        to_mongo_id = lookup.get(target_id)
        if not from_mongo_id or not to_mongo_id:
            continue

        e_type = edge.get("relation") or edge.get("type") or ""
        e_type_lower = e_type.lower()
        if e_type_lower in ("imports", "imports"):
            mapped_type = "IMPORTS"
        elif e_type_lower == "calls":
            mapped_type = "CALLS"
        elif e_type_lower == "defines":
            mapped_type = "DEFINES"
        elif e_type_lower == "implements":
            mapped_type = "IMPLEMENTS"
        else:
            mapped_type = e_type

        relation = edge.get("relation")
        await db.graph_edges.update_one(
            {
                "from_id": from_mongo_id,
                "to_id": to_mongo_id,
                "type": mapped_type,
            },
            {"$set": {
                "weight": None,
                "metadata": {"relation": relation},
                "created_at": now,
            }},
            upsert=True,
        )
        edges_created += 1

    # Step 5 — Ensure Repository node and File nodes exist for all chunked files (including text/markdown READMEs)
    repo_id_str = f"repo:{repo_name}"
    repo_node_id = hashlib.sha256(repo_id_str.encode()).hexdigest()[:24]

    await db.graph_nodes.update_one(
        {"_id": repo_node_id},
        {"$set": {
            "type": "Repository",
            "name": repo_name,
            "repo_name": repo_name,
            "file_path": "",
            "language": "text",
            "summary": f"Repository {repo_name}",
            "updated_at": now,
        }, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    nodes_created += 1

    cursor = db.code_chunks.find({"repo_name": repo_name}, {"file_path": 1})
    chunks = await cursor.to_list(length=None)
    chunked_files = {c["file_path"] for c in chunks if c.get("file_path")}

    # Also fetch files from documents collection for vault repositories
    doc_cursor = db.documents.find({"repo_name": repo_name}, {"original_filename": 1})
    doc_files = await doc_cursor.to_list(length=None)
    for df in doc_files:
        if df.get("original_filename"):
            chunked_files.add(df["original_filename"])

    for file_path in chunked_files:
        file_id_str = f"{repo_name}:{file_path}::file"
        file_node_id = hashlib.sha256(file_id_str.encode()).hexdigest()[:24]

        # Upsert File node
        await db.graph_nodes.update_one(
            {"_id": file_node_id},
            {"$set": {
                "type": "File",
                "name": file_path.split("/")[-1],
                "repo_name": repo_name,
                "file_path": file_path,
                "language": file_path.split(".")[-1].lower() if "." in file_path else "text",
                "summary": f"File {file_path} in {repo_name}",
                "updated_at": now,
            }, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        nodes_created += 1

        # Connect File node -> Repository node (PART_OF)
        await db.graph_edges.update_one(
            {
                "from_id": file_node_id,
                "to_id": repo_node_id,
                "type": "PART_OF",
            },
            {"$set": {
                "weight": None,
                "created_at": now,
            }},
            upsert=True,
        )
        edges_created += 1

    return nodes_created, edges_created


async def build_graph_from_document_chunks(
    chunks: list[ParsedChunk],
    chunk_ids: list[str],
    document_id: str,
    db
) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    nodes_created = 0
    edges_created = 0

    # Fetch document from DB
    from bson import ObjectId
    try:
        doc_oid = ObjectId(document_id) if ObjectId.is_valid(document_id) else document_id
        doc = await db.documents.find_one({"_id": doc_oid})
    except Exception:
        doc = await db.documents.find_one({"_id": document_id})

    if not doc:
        logger.warning("Document with ID %s not found for graph builder", document_id)
        return 0, 0

    doc_title = doc.get("title") or doc.get("original_filename") or "Document"
    filename = doc.get("original_filename") or ""

    # 1. Create Document node
    await db.graph_nodes.update_one(
        {"_id": document_id},
        {"$set": {
            "type": "Document",
            "name": doc_title,
            "file_path": filename,
            "updated_at": now,
        }, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    nodes_created += 1

    # 2. For each chunk: Section node + PART_OF edge to Document node
    for chunk, cid in zip(chunks, chunk_ids):
        await db.graph_nodes.update_one(
            {"_id": cid},
            {"$set": {
                "type": "Section",
                "name": chunk.name,
                "file_path": filename,
                "language": chunk.language or "text",
                "updated_at": now,
            }, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        nodes_created += 1

        # PART_OF edge: Section -> Document
        await _upsert_edge(db, cid, document_id, "PART_OF", now)
        edges_created += 1

    # 3. If project_id is set: create a REFERENCES edge from Document -> Project
    project_id = doc.get("project_id")
    if project_id:
        project_node_id = f"Project_{project_id}"
        try:
            proj_oid = ObjectId(project_id) if ObjectId.is_valid(project_id) else project_id
            proj_doc = await db.projects.find_one({"_id": proj_oid})
        except Exception:
            proj_doc = await db.projects.find_one({"_id": project_id})

        project_name = proj_doc.get("name") if proj_doc else "Project"
        await db.graph_nodes.update_one(
            {"_id": project_node_id},
            {"$set": {
                "type": "Project",
                "name": project_name,
                "updated_at": now,
            }, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        # Document REFERENCES Project
        await _upsert_edge(db, document_id, project_node_id, "REFERENCES", now)
        edges_created += 1

    # 4. Call GPT-4o in batches of 10 chunks to extract concepts
    settings = get_settings()
    if settings.OPENAI_API_KEY:
        client = _get_openai_client()
        for batch_start in range(0, len(chunks), 10):
            batch = chunks[batch_start : batch_start + 10]
            batch_cids = chunk_ids[batch_start : batch_start + 10]

            for chunk, cid in zip(batch, batch_cids):
                try:
                    resp = await client.chat.completions.create(
                        model=settings.OPENAI_CHAT_MODEL,
                        messages=[
                            {"role": "system", "content": CONCEPT_EXTRACTION_PROMPT},
                            {"role": "user", "content": chunk.content[:3000]},
                        ],
                        temperature=0.0,
                    )
                    raw = resp.choices[0].message.content.strip()
                    if raw.startswith("```"):
                        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
                    data = json.loads(raw)

                    # Upsert Concept nodes and REFERENCES edges
                    for concept in data.get("concepts", []):
                        concept_id = _node_id("Concept", concept)
                        await db.graph_nodes.update_one(
                            {"_id": concept_id},
                            {"$set": {
                                "type": "Concept",
                                "name": concept,
                                "updated_at": now,
                            }, "$setOnInsert": {"created_at": now}},
                            upsert=True,
                        )
                        # REFERENCES edge from Section -> Concept
                        await _upsert_edge(db, cid, concept_id, "REFERENCES", now)
                        nodes_created += 1
                        edges_created += 1

                    summary = data.get("one_line_summary", "")
                    if summary:
                        await db.graph_nodes.update_one(
                            {"_id": cid},
                            {"$set": {"summary": summary}},
                        )

                except Exception as exc:
                    logger.warning("Concept extraction failed for chunk %s: %s", cid, exc)

            await asyncio.sleep(0.5)

    return nodes_created, edges_created


async def build_similar_edges(repo_name: str, db) -> int:
    settings = get_settings()
    threshold = settings.SIMILARITY_THRESHOLD
    now = datetime.now(timezone.utc)

    # Fetch all code_chunks for this repo (only _id and embedding)
    # Cap at 500 chunks to prevent memory explosion on large repos
    cursor = db.code_chunks.find(
        {"repo_name": repo_name},
        {"_id": 1, "embedding": 1},
    ).limit(500)
    docs = await cursor.to_list(length=500)

    if len(docs) < 2:
        return 0

    ids = [doc["_id"] for doc in docs]
    # Build normalized matrix once
    matrix = np.array([doc["embedding"] for doc in docs], dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    matrix = matrix / norms

    # Free the raw docs list to reclaim memory
    del docs

    edges_created = 0
    batch_size = 50  # Process rows in batches to avoid holding full NxN in memory
    from pymongo import UpdateOne

    for batch_start in range(0, len(ids), batch_size):
        batch_end = min(batch_start + batch_size, len(ids))
        # Compute similarity only for this batch of rows against all columns
        batch_sims = matrix[batch_start:batch_end] @ matrix.T

        operations = []
        for local_i, global_i in enumerate(range(batch_start, batch_end)):
            scores = batch_sims[local_i]
            # Find indices above threshold, excluding self, take top 3
            candidates = []
            for j in range(len(ids)):
                if j != global_i and scores[j] >= threshold:
                    candidates.append((j, float(scores[j])))
            candidates.sort(key=lambda x: x[1], reverse=True)

            for j, score in candidates[:3]:
                operations.append(
                    UpdateOne(
                        {
                            "from_id": ids[global_i],
                            "to_id": ids[j],
                            "type": "SIMILAR_TO",
                        },
                        {"$setOnInsert": {
                            "from_id": ids[global_i],
                            "to_id": ids[j],
                            "type": "SIMILAR_TO",
                            "weight": score,
                            "created_at": now,
                        }},
                        upsert=True,
                    )
                )

        if operations:
            try:
                result = await db.graph_edges.bulk_write(operations, ordered=False)
                edges_created += result.upserted_count
            except Exception as exc:
                logger.warning("bulk_write for SIMILAR_TO edges failed: %s", exc)

        # Free batch similarity sub-matrix
        del batch_sims
        await asyncio.sleep(0)  # yield to event loop

    # Free the full normalized matrix
    del matrix

    logger.info("Created %d SIMILAR_TO edges for repo %s", edges_created, repo_name)
    return edges_created


async def _upsert_edge(db, from_id: str, to_id: str, edge_type: str, now: datetime) -> None:
    existing = await db.graph_edges.find_one({
        "from_id": from_id,
        "to_id": to_id,
        "type": edge_type,
    })
    if not existing:
        await db.graph_edges.insert_one({
            "from_id": from_id,
            "to_id": to_id,
            "type": edge_type,
            "weight": None,
            "created_at": now,
        })


async def build_overall_graph(vault_dir: str, db=None) -> None:
    now = datetime.now(timezone.utc)
    import shutil
    
    # Clean up old overall nodes and edges from MongoDB first
    if db is not None:
        try:
            overall_node_ids = []
            async for node in db.graph_nodes.find({"repo_name": "overall"}, {"_id": 1}):
                overall_node_ids.append(node["_id"])
            
            if overall_node_ids:
                await db.graph_edges.delete_many({
                    "$or": [
                        {"from_id": {"$in": overall_node_ids}},
                        {"to_id": {"$in": overall_node_ids}}
                    ]
                })
                await db.graph_nodes.delete_many({"repo_name": "overall"})
                logger.info("Cleared %d old overall nodes and their edges from DB", len(overall_node_ids))
        except Exception as exc:
            logger.warning("Failed to clean up old overall graph nodes/edges: %s", exc)

    # Resolve graphify binary path
    import sys
    sys_dir = os.path.dirname(sys.executable)
    graphify_bin = os.path.join(sys_dir, "graphify.exe" if os.name == "nt" else "graphify")
    if not os.path.exists(graphify_bin):
        graphify_bin = "graphify"

    settings = get_settings()
    env = {**os.environ}
    if settings.OPENAI_API_KEY:
        env["AZURE_OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    if settings.OPENAI_ENDPOINT:
        env["AZURE_OPENAI_ENDPOINT"] = settings.OPENAI_ENDPOINT
    if settings.OPENAI_API_VERSION:
        env["AZURE_OPENAI_API_VERSION"] = settings.OPENAI_API_VERSION
    if settings.OPENAI_CHAT_MODEL:
        env["AZURE_OPENAI_DEPLOYMENT"] = settings.OPENAI_CHAT_MODEL
        env["GRAPHIFY_AZURE_MODEL"] = settings.OPENAI_CHAT_MODEL

    wiki_dir = os.path.join(vault_dir, "wiki")
    input_dir = wiki_dir if os.path.isdir(wiki_dir) else vault_dir

    # Reset graphify-out folder in vault_dir to prevent stale artifacts
    graphify_out_dir = os.path.join(vault_dir, "graphify-out")
    if os.path.exists(graphify_out_dir):
        shutil.rmtree(graphify_out_dir, ignore_errors=True)
    os.makedirs(graphify_out_dir, exist_ok=True)

    import subprocess
    def run_graphify():
        return subprocess.run(
            [graphify_bin, "extract", input_dir, "--backend", "azure", "--out", vault_dir],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    try:
        logger.info("Running overall graphify on wiki corpus: %s", input_dir)
        res = await asyncio.to_thread(run_graphify)
        if res.returncode != 0:
            logger.warning(f"Graphify overall extraction failed: {res.stderr.decode(errors='ignore')}")
        elif db is not None:
            logger.info("Successfully generated overall graphify artifacts at %s/graphify-out", vault_dir)
            
            # Read and parse the overall graphify-out/graph.json
            import json
            graph_path = os.path.join(vault_dir, "graphify-out", "graph.json")
            if not os.path.exists(graph_path):
                graph_path = os.path.join(vault_dir, "graph.json")

            if os.path.exists(graph_path):
                try:
                    with open(graph_path, "r", encoding="utf-8", errors="ignore") as f:
                        graph_data = json.load(f)
                        graphify_nodes = graph_data.get("nodes", [])
                        graphify_edges = graph_data.get("edges", [])

                    # Map and upsert overall nodes
                    lookup = {}
                    for node in graphify_nodes:
                        file_path = node.get("source_file") or node.get("file") or ""
                        name = node.get("label") or node.get("name") or ""
                        g_type = node.get("file_type") or node.get("type") or ""

                        # Type mapping
                        g_type_lower = g_type.lower()
                        if g_type_lower in ("function", "method"):
                            n_type = "Function"
                        elif g_type_lower == "class":
                            n_type = "Class"
                        elif g_type_lower in ("file", "module"):
                            n_type = "File"
                        elif g_type_lower in ("concept", "theme", "community"):
                            n_type = "Concept"
                        else:
                            n_type = g_type.capitalize() if g_type else "Other"

                        # Try to resolve repo_name from file_path if possible
                        # e.g., wiki/sudhirMahaaraja/README.md.md
                        parts = file_path.replace("\\", "/").split("/")
                        node_repo = "overall"
                        if len(parts) >= 3 and parts[0] == "wiki":
                            node_repo = parts[1]

                        id_str = f"{node_repo}:{file_path}:{name}:{g_type}"
                        mongo_id = hashlib.sha256(id_str.encode()).hexdigest()[:24]

                        # Infer language
                        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
                        ext_map = {
                            "py": "python",
                            "js": "javascript",
                            "jsx": "javascript",
                            "ts": "typescript",
                            "tsx": "typescript",
                            "html": "html",
                            "css": "css",
                            "java": "java",
                            "cpp": "cpp",
                            "c": "c",
                            "h": "c",
                            "go": "go",
                            "sh": "shell",
                            "sql": "sql",
                            "md": "markdown",
                            "txt": "text",
                            "json": "json",
                        }
                        language = ext_map.get(ext, "text")

                        await db.graph_nodes.update_one(
                            {"_id": mongo_id},
                            {"$set": {
                                "type": n_type,
                                "name": name,
                                "repo_name": node_repo,
                                "file_path": file_path,
                                "language": language,
                                "summary": node.get("summary"),
                                "metadata": {
                                    "graphify_id": node.get("id"),
                                    "graphify_type": g_type,
                                },
                                "updated_at": now,
                            }, "$setOnInsert": {"created_at": now}},
                            upsert=True,
                        )
                        lookup[node["id"]] = mongo_id

                    # Map and upsert overall edges
                    for edge in graphify_edges:
                        source_id = edge.get("source")
                        target_id = edge.get("target")

                        from_mongo_id = lookup.get(source_id)
                        to_mongo_id = lookup.get(target_id)
                        if not from_mongo_id or not to_mongo_id:
                            continue

                        e_type = edge.get("relation") or edge.get("type") or ""
                        e_type_lower = e_type.lower()
                        if e_type_lower in ("imports", "imports"):
                            mapped_type = "IMPORTS"
                        elif e_type_lower == "calls":
                            mapped_type = "CALLS"
                        elif e_type_lower == "defines":
                            mapped_type = "DEFINES"
                        elif e_type_lower == "implements":
                            mapped_type = "IMPLEMENTS"
                        else:
                            mapped_type = e_type

                        relation = edge.get("relation")
                        await db.graph_edges.update_one(
                            {
                                "from_id": from_mongo_id,
                                "to_id": to_mongo_id,
                                "type": mapped_type,
                            },
                            {"$set": {
                                "weight": None,
                                "metadata": {"relation": relation},
                                "created_at": now,
                            }},
                            upsert=True,
                        )
                    logger.info("Successfully loaded overall graph nodes and edges to DB")
                except Exception as exc:
                    logger.warning(f"Failed to read or parse overall graph.json: {exc}")
    except Exception as exc:
        logger.warning(f"Failed to generate overall graph: {exc}")


async def update_index_connections(db) -> None:
    from pathlib import Path
    now = datetime.now(timezone.utc)
    
    # 1. Ensure the Wiki Index node exists
    index_id = "wiki_index"
    await db.graph_nodes.update_one(
        {"_id": index_id},
        {"$set": {
            "type": "Document",
            "name": "Wiki Index",
            "file_path": "index.md",
            "language": "markdown",
            "summary": "Main index containing all repositories and documents.",
            "updated_at": now,
        }, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )

    # 2. Delete all existing edges to/from the Wiki Index node
    await db.graph_edges.delete_many({
        "$or": [
            {"from_id": index_id},
            {"to_id": index_id}
        ]
    })

    # 3. Connect every Repository node to Wiki Index
    async for repo_node in db.graph_nodes.find({"type": "Repository"}):
        await db.graph_edges.update_one(
            {
                "from_id": repo_node["_id"],
                "to_id": index_id,
                "type": "INDEXED_IN"
            },
            {"$set": {"created_at": now}},
            upsert=True,
        )

    # 4. Connect every Project node to Wiki Index
    async for proj_node in db.graph_nodes.find({"type": "Project"}):
        await db.graph_edges.update_one(
            {
                "from_id": proj_node["_id"],
                "to_id": index_id,
                "type": "INDEXED_IN"
            },
            {"$set": {"created_at": now}},
            upsert=True,
        )

    # 5. Connect every Document node (excluding wiki_index) to Wiki Index
    async for doc_node in db.graph_nodes.find({"type": "Document", "_id": {"$ne": index_id}}):
        await db.graph_edges.update_one(
            {
                "from_id": doc_node["_id"],
                "to_id": index_id,
                "type": "INDEXED_IN"
            },
            {"$set": {"created_at": now}},
            upsert=True,
        )
        
    # Also sync the content of index.md into document_chunks for wiki_index
    from app.controllers.vault_manager import resolve_vault_dir
    settings = get_settings()
    vault_dir = resolve_vault_dir(settings.VAULT_PATH)
    index_file = vault_dir / "wiki" / "index.md"
    if index_file.exists():
        content = index_file.read_text(encoding="utf-8", errors="replace")
        await db.document_chunks.update_one(
            {"document_id": index_id, "page_number": 0},
            {"$set": {
                "content": content,
                "document_id": index_id,
                "page_number": 0,
                "updated_at": now,
            }, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )

