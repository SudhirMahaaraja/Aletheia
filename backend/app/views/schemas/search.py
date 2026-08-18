from typing import Optional

from pydantic import BaseModel


class ScoredResult(BaseModel):
    chunk_id: str
    score: float
    collection: str  # "code_chunks" | "document_chunks"
    payload: dict


class SearchResultResponse(BaseModel):
    results: list[ScoredResult]
    query: str
    total: int
