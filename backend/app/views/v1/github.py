import logging
from datetime import datetime, timezone

from bson import ObjectId
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import get_settings
from app.core.dependencies import require_admin, require_developer
from app.db.mongodb import get_db
from app.models.user import UserInDB
from app.views.schemas.github import ConnectRequest, ConnectResponse, RepoInfo, SelectRepoRequest, ActivateConnectionRequest
from app.controllers import github_controller

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["github"])


@router.post("/connect", response_model=ConnectResponse)
async def connect_github(
    body: ConnectRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(require_admin),
) -> ConnectResponse:
    user_login = await github_controller.validate_pat(body.pat, body.org_name)
    
    # 1. Deactivate all existing connections
    await db.github_connections.update_many({}, {"$set": {"active": False}})
    
    # 2. Upsert connection to DB
    await db.github_connections.update_one(
        {"user_login": user_login, "org_name": body.org_name or ""},
        {"$set": {
            "pat": body.pat,
            "org_name": body.org_name or "",
            "user_login": user_login,
            "active": True,
            "updated_at": datetime.now(timezone.utc),
        }},
        upsert=True
    )
    
    return ConnectResponse(valid=True, user_login=user_login)


@router.get("/connections")
async def list_connections(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(require_admin),
) -> list[dict]:
    connections = []
    async for conn in db.github_connections.find({}):
        connections.append({
            "id": str(conn["_id"]),
            "user_login": conn.get("user_login", ""),
            "org_name": conn.get("org_name", ""),
            "active": conn.get("active", False),
            "updated_at": conn.get("updated_at", ""),
        })
    return connections


@router.post("/connections/activate")
async def activate_connection(
    body: ActivateConnectionRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(require_admin),
) -> dict:
    # Deactivate all
    await db.github_connections.update_many({}, {"$set": {"active": False}})
    
    # Activate selected
    result = await db.github_connections.update_one(
        {"user_login": body.user_login, "org_name": body.org_name},
        {"$set": {"active": True}}
    )
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub connection not found"
        )
    return {"message": f"GitHub account {body.user_login} activated."}


@router.delete("/connections")
async def delete_connection(
    user_login: str,
    org_name: str = "",
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(require_admin),
) -> dict:
    result = await db.github_connections.delete_one(
        {"user_login": user_login, "org_name": org_name}
    )
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub connection not found"
        )
    
    # If the active one was deleted, make another one active
    active_exists = await db.github_connections.find_one({"active": True})
    if not active_exists:
        new_active = await db.github_connections.find_one({}, sort=[("updated_at", -1)])
        if new_active:
            await db.github_connections.update_one(
                {"_id": new_active["_id"]},
                {"$set": {"active": True}}
            )
            
    return {"message": "GitHub connection deleted successfully."}



@router.get("/repos")
async def list_repos(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(require_developer),
) -> list[dict]:
    try:
        repos = await github_controller.list_all_repos(db)
    except Exception as exc:
        logger.warning("Failed to fetch repositories from GitHub API: %s", exc)
        repos = []

    # Get all repositories in the database
    db_repos = []
    try:
        async for repo in db.repositories.find({}):
            db_repos.append(repo)
    except Exception as exc:
        logger.error("Failed to query repositories collection: %s", exc)

    result = []
    seen = set()

    for r in repos:
        repo_doc = next((d for d in db_repos if d["github_full_name"] == r.full_name), None)
        is_selected = False
        selected_branch = ""
        ingestion_status = "never"
        if repo_doc:
            ingestion_status = repo_doc.get("ingestion_status", "never")
            is_selected = repo_doc.get("is_selected", False) or ingestion_status == "done"
            selected_branch = repo_doc.get("selected_branch", "")
        
        result.append({
            "full_name": r.full_name,
            "name": r.name,
            "description": r.description,
            "language": r.language,
            "default_branch": r.default_branch,
            "is_selected": is_selected,
            "selected_branch": selected_branch,
            "ingestion_status": ingestion_status,
        })
        seen.add(r.full_name)

    # Append any repository from database that was not in GitHub API response
    for repo_doc in db_repos:
        full_name = repo_doc["github_full_name"]
        if full_name not in seen:
            ingestion_status = repo_doc.get("ingestion_status", "never")
            is_selected = repo_doc.get("is_selected", False) or ingestion_status == "done"
            result.append({
                "full_name": full_name,
                "name": repo_doc.get("name") or full_name.split("/")[-1],
                "description": repo_doc.get("description", ""),
                "language": repo_doc.get("language", ""),
                "default_branch": repo_doc.get("selected_branch", "main"),
                "is_selected": is_selected,
                "selected_branch": repo_doc.get("selected_branch", ""),
                "ingestion_status": ingestion_status,
            })
            seen.add(full_name)

    return result


@router.get("/repos/{repo_full_name:path}/branches")
async def get_branches(
    repo_full_name: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(require_admin),
) -> list[str]:
    return await github_controller.get_repo_branches(repo_full_name, db)


@router.post("/repos/select")
async def select_repo(
    body: SelectRepoRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(require_admin),
) -> dict:
    now = datetime.now(timezone.utc)

    # Fetch repo info from GitHub to get metadata
    repos = await github_controller.list_all_repos(db)
    repo_info = None
    for r in repos:
        if r.full_name == body.repo_full_name:
            repo_info = r
            break

    repo_doc = {
        "github_full_name": body.repo_full_name,
        "name": repo_info.name if repo_info else body.repo_full_name.split("/")[-1],
        "description": repo_info.description if repo_info else "",
        "language": repo_info.language if repo_info else "",
        "selected_branch": body.branch,
        "is_selected": True,
        "ingestion_status": "never",
        "total_files": 0,
        "total_chunks": 0,
        "added_at": now,
    }

    try:
        result = await db.repositories.update_one(
            {"github_full_name": body.repo_full_name},
            {"$set": repo_doc},
            upsert=True,
        )
        # Get the document to return its ID
        saved = await db.repositories.find_one({"github_full_name": body.repo_full_name})
        repo_id = str(saved["_id"])
    except Exception as exc:
        logger.error("Failed to select repo: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to select repository",
        )

    return {"repository_id": repo_id, "message": f"Repository {body.repo_full_name} selected on branch {body.branch}"}


@router.delete("/repos/{repo_full_name:path}/deselect")
async def deselect_repo(
    repo_full_name: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(require_admin),
) -> dict:
    result = await db.repositories.update_one(
        {"github_full_name": repo_full_name},
        {"$set": {"is_selected": False}},
    )
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    return {"message": f"Repository {repo_full_name} deselected"}


@router.delete("/repos/{repo_full_name:path}")
async def delete_ingested_repo(
    repo_full_name: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(require_admin),
) -> dict:
    """
    Completely deletes an ingested repository from the database and the local vault.
    """
    # 1. Check if repository exists in DB
    repo = await db.repositories.find_one({"github_full_name": repo_full_name})
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository '{repo_full_name}' not found."
        )

    # 2. Delete chunks from code_chunks
    await db.code_chunks.delete_many({"repo_name": repo_full_name})

    # 3. Find and delete documents associated with this repository
    doc_ids = []
    async for doc in db.documents.find({"repo_name": repo_full_name}, {"_id": 1}):
        doc_ids.append(doc["_id"])

    if doc_ids:
        # Delete document chunks
        await db.document_chunks.delete_many({"document_id": {"$in": doc_ids}})
        # Delete document records
        await db.documents.delete_many({"_id": {"$in": doc_ids}})

    # 4. Find and delete graph nodes associated with this repository
    # Graph nodes can have repo_name matching repo_full_name or the overall slug
    node_ids = []
    async for node in db.graph_nodes.find({
        "$or": [
            {"repo_name": repo_full_name},
            {"repo_name": repo_full_name.replace("/", "--")}
        ]
    }, {"_id": 1}):
        node_ids.append(node["_id"])

    if node_ids:
        # Delete edges connected to these nodes
        await db.graph_edges.delete_many({
            "$or": [
                {"from_id": {"$in": node_ids}},
                {"to_id": {"$in": node_ids}}
            ]
        })
        # Delete the nodes
        await db.graph_nodes.delete_many({"_id": {"$in": node_ids}})

    # 5. Delete repository from repositories collection
    await db.repositories.delete_one({"github_full_name": repo_full_name})

    # 6. Delete directory files from local vault
    settings = get_settings()
    from app.controllers.vault_manager import repo_slug, rebuild_index, resolve_vault_dir, ensure_vault_structure
    vault_dir = resolve_vault_dir(settings.VAULT_PATH)
    slug = repo_slug(repo_full_name)
    paths = ensure_vault_structure(vault_dir)
    
    import shutil
    raw_repo_dir = paths["raw_repositories"] / slug
    wiki_repo_dir = paths["wiki_repositories"] / slug
    repo_graph_dir = paths["repo_graphs"] / slug

    if raw_repo_dir.exists():
        shutil.rmtree(raw_repo_dir, ignore_errors=True)
    if wiki_repo_dir.exists():
        shutil.rmtree(wiki_repo_dir, ignore_errors=True)
    if repo_graph_dir.exists():
        shutil.rmtree(repo_graph_dir, ignore_errors=True)

    # 7. Rebuild vault index
    rebuild_index(vault_dir)

    # 8. Sync wiki meta files (index.md, log.md) and update index connections
    from app.controllers.ingestion.pipeline import sync_wiki_meta_to_db
    from app.controllers.ingestion.graph_builder import update_index_connections, build_overall_graph
    
    await sync_wiki_meta_to_db(vault_dir, db)
    await update_index_connections(db)

    # 9. Rebuild overall graphify graph
    await build_overall_graph(str(vault_dir), db)

    return {"message": f"Repository {repo_full_name} and all its ingested code, documents, and graph connections have been deleted."}
