from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class IngestionJobInDB(BaseModel):
    id: str = ""
    job_type: str  # "repo" | "document"
    source_id: str
    source_name: str
    status: str = "queued"  # "queued" | "running" | "done" | "failed"
    files_total: int = 0
    files_processed: int = 0
    chunks_created: int = 0
    nodes_created: int = 0
    edges_created: int = 0
    errors: list[str] = []
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    triggered_by: str = ""
