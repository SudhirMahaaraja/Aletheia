import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.dependencies import get_current_user
from app.db.mongodb import get_db
from app.models.user import UserInDB
from app.views.schemas.search import SearchResultResponse, ScoredResult
from app.controllers import vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResultResponse)
async def search_knowledge_base(
    q: str = Query(..., description="The search query text"),
    repo_filter: Optional[List[str]] = Query(None, description="Optional list of repositories to filter code results"),
    top_k: int = Query(10, ge=1, le=50, description="Max number of results to return"),
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Search across code repositories and uploaded documents using semantic vector search.
    """
    results = await vector_store.search_all(
        db=db,
        query=q,
        top_k=top_k,
        repo_filter=repo_filter,
    )

    scored_results = []
    for r in results:
        scored_results.append(ScoredResult(
            chunk_id=r["chunk_id"],
            score=r["score"],
            collection=r["collection"],
            payload=r["payload"],
        ))

    return SearchResultResponse(
        results=scored_results,
        query=q,
        total=len(scored_results),
    )
