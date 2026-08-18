from fastapi import APIRouter

from app.views.v1.auth import router as auth_router
from app.views.v1.github import router as github_router
from app.views.v1.ingest import router as ingest_router
from app.views.v1.chat import router as chat_router
from app.views.v1.search import router as search_router
from app.views.v1.graph import router as graph_router
from app.views.v1.admin import router as admin_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(github_router)
router.include_router(ingest_router)
router.include_router(chat_router)
router.include_router(search_router)
router.include_router(graph_router)
router.include_router(admin_router)

