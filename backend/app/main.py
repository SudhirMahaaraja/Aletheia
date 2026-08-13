import sys
import os
import warnings

# Suppress HuggingFace optimum warnings, deprecation warnings, and user warnings
warnings.filterwarnings("ignore")

# Resolve parent directory containing the "app" package
app_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(app_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging_config import setup_logging
from app.db.mongodb import mongodb_client
from app.controllers import auth_controller

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    setup_logging()
    logger.info("Starting BWS Second Brain ...")
    await mongodb_client.connect()
    db = mongodb_client.get_db()
    await auth_controller.ensure_admin_exists(db)

    # Backfill Repository and File nodes in graph_nodes in the background
    async def backfill_nodes(db):
        try:
            import hashlib
            from datetime import datetime, timezone
            
            # Sync the vault disk files to DB first
            from app.controllers.ingestion.pipeline import sync_vault_to_db
            await sync_vault_to_db(db)

            async for repo in db.repositories.find({"ingestion_status": "done"}):
                repo_name = repo["github_full_name"]
                logger.info("Backfilling Repository and File nodes for existing repo: %s", repo_name)
                
                now = datetime.now(timezone.utc)
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
                
                cursor = db.code_chunks.find({"repo_name": repo_name}, {"file_path": 1})
                chunks = await cursor.to_list(length=None)
                chunked_files = {c["file_path"] for c in chunks if c.get("file_path")}

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

                    # Connect File node -> Repository node
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
            # Ensure the Wiki Index node and connections are up-to-date
            from app.controllers.ingestion.graph_builder import update_index_connections
            await update_index_connections(db)
            
            logger.info("Background Repository and File node backfill completed successfully.")
        except Exception as exc:
            logger.error("Failed to backfill repository and file nodes: %s", exc)

    async def cleanup_expired_documents():
        import time
        from app.core.config import get_settings
        from app.controllers.vault_manager import resolve_vault_dir
        
        settings = get_settings()
        vault_dir = resolve_vault_dir(settings.VAULT_PATH)
        generated_dir = vault_dir / "generated"
        
        while True:
            try:
                if generated_dir.is_dir():
                    now = time.time()
                    for f in generated_dir.glob("*.docx"):
                        if now - f.stat().st_mtime > 900:
                            try:
                                f.unlink()
                                logger.info("Cleaned up expired generated document: %s", f.name)
                            except Exception as e:
                                logger.error("Failed to delete expired file %s: %s", f.name, e)
            except Exception as e:
                logger.error("Error in generated document cleanup: %s", e)
            await asyncio.sleep(60)

    import asyncio
    asyncio.create_task(backfill_nodes(db))
    asyncio.create_task(cleanup_expired_documents())
    logger.info("BWS Second Brain ready")
    yield
    # Shutdown
    await mongodb_client.disconnect()
    logger.info("BWS Second Brain shut down")


settings = get_settings()

app = FastAPI(
    title="BWS Second Brain",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and include the v1 router
from app.views.v1.router import router as v1_router  # noqa: E402

app.include_router(v1_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}


# Serve React build
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend", "dist")
if not os.path.exists(frontend_dir):
    os.makedirs(frontend_dir, exist_ok=True)
    with open(os.path.join(frontend_dir, "index.html"), "w") as f:
        f.write("<h1>React build is not generated yet. Run npm run build in frontend directory first.</h1>")


@app.exception_handler(StarletteHTTPException)
async def spa_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and not request.url.path.startswith("/api"):
        index_file = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
    return await http_exception_handler(request, exc)


app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
