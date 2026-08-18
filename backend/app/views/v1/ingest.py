import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.dependencies import get_current_user, require_admin
from app.db.mongodb import get_db
from app.models.user import UserInDB
from app.views.schemas.ingest import IngestDocumentResponse, IngestJobResponse, IngestRepoRequest, JobDetailResponse, ProjectResponse, CreateProjectRequest
from app.controllers.ingestion import pipeline

logger = logging.getLogger(__name__)


def _format_datetime(dt) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat().replace("+00:00", "Z")


router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/repo", response_model=IngestJobResponse)
async def ingest_repo(
    body: IngestRepoRequest,
    background_tasks: BackgroundTasks,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(require_admin),
) -> IngestJobResponse:
    # Find repo in DB
    repo_doc = await db.repositories.find_one({"github_full_name": body.repo_full_name})
    if not repo_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository '{body.repo_full_name}' not found. Select it first via POST /github/repos/select",
        )

    if not repo_doc.get("is_selected"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Repository '{body.repo_full_name}' is not selected for ingestion",
        )

    now = datetime.now(timezone.utc)
    job_id = str(ObjectId())

    job_doc = {
        "_id": job_id,
        "job_type": "repo",
        "source_id": str(repo_doc["_id"]),
        "source_name": body.repo_full_name,
        "status": "queued",
        "files_total": 0,
        "files_processed": 0,
        "chunks_created": 0,
        "nodes_created": 0,
        "edges_created": 0,
        "errors": [],
        "started_at": None,
        "completed_at": None,
        "triggered_by": current_user.id,
    }
    await db.ingestion_jobs.insert_one(job_doc)

    # Mark repo as queued
    await db.repositories.update_one(
        {"_id": repo_doc["_id"]},
        {"$set": {"ingestion_status": "queued"}},
    )

    branch = repo_doc.get("selected_branch", "main")
    background_tasks.add_task(
        pipeline.ingest_repository,
        job_id=job_id,
        repo_full_name=body.repo_full_name,
        branch=branch,
        db=db,
    )

    return IngestJobResponse(job_id=job_id, status="queued")


@router.post("/repo-to-vault", response_model=IngestJobResponse)
async def ingest_repo_to_vault_endpoint(
    body: IngestRepoRequest,
    background_tasks: BackgroundTasks,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(require_admin),
) -> IngestJobResponse:
    # Find repo in DB
    repo_doc = await db.repositories.find_one({"github_full_name": body.repo_full_name})
    if not repo_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository '{body.repo_full_name}' not found. Select it first.",
        )

    now = datetime.now(timezone.utc)
    job_id = str(ObjectId())

    job_doc = {
        "_id": job_id,
        "job_type": "vault_repo",
        "source_id": str(repo_doc["_id"]),
        "source_name": body.repo_full_name,
        "status": "queued",
        "files_total": 0,
        "files_processed": 0,
        "chunks_created": 0,
        "nodes_created": 0,
        "edges_created": 0,
        "errors": [],
        "started_at": None,
        "completed_at": None,
        "triggered_by": current_user.id,
    }
    await db.ingestion_jobs.insert_one(job_doc)

    # Mark repo as queued
    await db.repositories.update_one(
        {"_id": repo_doc["_id"]},
        {"$set": {"ingestion_status": "queued"}},
    )

    branch = repo_doc.get("selected_branch", "main")
    background_tasks.add_task(
        pipeline.ingest_repo_to_local_vault,
        job_id=job_id,
        repo_full_name=body.repo_full_name,
        branch=branch,
        db=db,
    )

    return IngestJobResponse(job_id=job_id, status="queued")


@router.post("/document", response_model=IngestDocumentResponse)
async def ingest_document_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(""),
    project_id: Optional[str] = Form(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user),
) -> IngestDocumentResponse:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File name is required",
        )

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    allowed = {"pdf", "docx", "md", "txt"}
    if ext not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '.{ext}'. Allowed: {', '.join(allowed)}",
        )

    file_bytes = await file.read()
    now = datetime.now(timezone.utc)
    doc_id = str(ObjectId())
    job_id = str(ObjectId())

    # Create document record
    doc_record = {
        "_id": doc_id,
        "title": title or file.filename,
        "original_filename": file.filename,
        "file_type": ext,
        "project_id": project_id,
        "uploaded_by": current_user.id,
        "uploaded_at": now,
        "ingestion_status": "queued",
        "total_chunks": 0,
        "file_size_bytes": len(file_bytes),
    }
    await db.documents.insert_one(doc_record)

    # Create job record
    job_doc = {
        "_id": job_id,
        "job_type": "document",
        "source_id": doc_id,
        "source_name": file.filename,
        "status": "queued",
        "files_total": 1,
        "files_processed": 0,
        "chunks_created": 0,
        "nodes_created": 0,
        "edges_created": 0,
        "errors": [],
        "started_at": None,
        "completed_at": None,
        "triggered_by": current_user.id,
    }
    await db.ingestion_jobs.insert_one(job_doc)

    background_tasks.add_task(
        pipeline.ingest_document,
        job_id=job_id,
        document_id=doc_id,
        file_bytes=file_bytes,
        filename=file.filename,
        file_type=ext,
        db=db,
    )

    return IngestDocumentResponse(job_id=job_id, document_id=doc_id, status="queued")


@router.get("/jobs")
async def list_jobs(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user),
) -> list[JobDetailResponse]:
    cursor = db.ingestion_jobs.find({}).sort("started_at", -1).limit(50)
    jobs = await cursor.to_list(length=50)
    result = []
    for j in jobs:
        result.append(JobDetailResponse(
            job_id=str(j["_id"]),
            job_type=j.get("job_type", ""),
            source_id=j.get("source_id", ""),
            source_name=j.get("source_name", ""),
            status=j.get("status", ""),
            files_total=j.get("files_total", 0),
            files_processed=j.get("files_processed", 0),
            chunks_created=j.get("chunks_created", 0),
            nodes_created=j.get("nodes_created", 0),
            edges_created=j.get("edges_created", 0),
            errors=j.get("errors", []),
            started_at=_format_datetime(j.get("started_at")),
            completed_at=_format_datetime(j.get("completed_at")),
            triggered_by=j.get("triggered_by", ""),
            current_file=j.get("current_file"),
        ))
    return result


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user),
) -> JobDetailResponse:
    j = await db.ingestion_jobs.find_one({"_id": job_id})
    if not j:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobDetailResponse(
        job_id=str(j["_id"]),
        job_type=j.get("job_type", ""),
        source_id=j.get("source_id", ""),
        source_name=j.get("source_name", ""),
        status=j.get("status", ""),
        files_total=j.get("files_total", 0),
        files_processed=j.get("files_processed", 0),
        chunks_created=j.get("chunks_created", 0),
        nodes_created=j.get("nodes_created", 0),
        edges_created=j.get("edges_created", 0),
        errors=j.get("errors", []),
        started_at=_format_datetime(j.get("started_at")),
        completed_at=_format_datetime(j.get("completed_at")),
        triggered_by=j.get("triggered_by", ""),
        current_file=j.get("current_file"),
    )


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(require_admin),
) -> dict:
    """
    Deletes an ingestion job record from the database.
    """
    try:
        j = await db.ingestion_jobs.find_one({"_id": job_id})
    except Exception:
        j = None
    if not j:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    await db.ingestion_jobs.delete_one({"_id": job_id})
    return {"status": "success", "message": f"Job '{job_id}' has been removed from the queue."}



@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user),
) -> list[ProjectResponse]:
    cursor = db.projects.find({}).sort("name", 1)
    projects = await cursor.to_list(length=1000)
    result = []
    for p in projects:
        result.append(ProjectResponse(
            id=str(p["_id"]),
            name=p["name"],
            description=p.get("description"),
            created_at=_format_datetime(p.get("created_at")) or _format_datetime(datetime.now(timezone.utc)),
        ))
    return result


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: CreateProjectRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user),
) -> ProjectResponse:
    # Check if project already exists
    existing = await db.projects.find_one({"name": body.name})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project with name '{body.name}' already exists."
        )
        
    project_id = str(ObjectId())
    now = datetime.now(timezone.utc)
    project_doc = {
        "_id": project_id,
        "name": body.name,
        "description": body.description,
        "created_at": now,
    }
    await db.projects.insert_one(project_doc)
    
    # Also create a graph node for the project so it shows in the directory immediately
    project_node_id = f"Project_{project_id}"
    await db.graph_nodes.update_one(
        {"_id": project_node_id},
        {"$set": {
            "type": "Project",
            "name": body.name,
            "updated_at": now,
        }, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    
    from app.controllers.ingestion.graph_builder import update_index_connections
    await update_index_connections(db)
    
    return ProjectResponse(
        id=project_id,
        name=body.name,
        description=body.description,
        created_at=_format_datetime(now),
    )


@router.delete("/document/{document_id}")
async def delete_document(
    document_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(require_admin),
) -> dict:
    """
    Completely deletes an uploaded document from the database and the local vault.
    """
    # 1. Find document in DB
    try:
        doc_oid = ObjectId(document_id) if ObjectId.is_valid(document_id) else document_id
        doc = await db.documents.find_one({"_id": doc_oid})
    except Exception:
        doc = await db.documents.find_one({"_id": document_id})

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )

    # 2. Delete chunks from document_chunks
    await db.document_chunks.delete_many({"document_id": document_id})

    # 3. Find and delete graph nodes associated with this document
    node_ids = [document_id]
    async for node in db.graph_nodes.find({"type": "Section", "file_path": doc.get("original_filename")}, {"_id": 1}):
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

    # 4. Delete document record
    try:
        if isinstance(doc["_id"], ObjectId):
            await db.documents.delete_one({"_id": doc["_id"]})
        else:
            await db.documents.delete_one({"_id": document_id})
    except Exception:
        await db.documents.delete_one({"_id": document_id})

    # 5. Delete directory files from local vault
    from app.core.config import get_settings
    from app.controllers.vault_manager import resolve_vault_dir, rebuild_index
    settings = get_settings()
    vault_dir = resolve_vault_dir(settings.VAULT_PATH)
    
    import shutil
    raw_path = doc.get("vault_raw_path")
    wiki_path = doc.get("vault_wiki_path")

    if raw_path:
        if raw_path.startswith("raw/"):
            raw_file = vault_dir.parent / raw_path
        else:
            raw_file = vault_dir / raw_path
        if raw_file.exists():
            raw_file.unlink(missing_ok=True)
    if wiki_path:
        wiki_file = vault_dir / wiki_path
        if wiki_file.exists():
            wiki_file.unlink(missing_ok=True)

    # 6. Rebuild vault index
    rebuild_index(vault_dir)

    # 7. Sync wiki meta files (index.md, log.md) and update index connections
    from app.controllers.ingestion.pipeline import sync_wiki_meta_to_db
    from app.controllers.ingestion.graph_builder import update_index_connections, build_overall_graph
    
    await sync_wiki_meta_to_db(vault_dir, db)
    await update_index_connections(db)

    # 8. Rebuild overall graphify graph
    await build_overall_graph(str(vault_dir), db)

    return {"message": f"Document '{doc.get('title')}' and all its chunks and graph connections have been deleted."}

