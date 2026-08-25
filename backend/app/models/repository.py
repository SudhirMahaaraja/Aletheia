from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class RepositoryInDB(BaseModel):
    id: str = ""
    github_full_name: str
    name: str
    description: str = ""
    language: str = ""
    project_id: Optional[str] = None
    selected_branch: str = "main"
    is_selected: bool = False
    last_ingested_at: Optional[datetime] = None
    ingestion_status: str = "never"  # "never" | "queued" | "running" | "done" | "failed"
    total_files: int = 0
    total_chunks: int = 0
    added_at: Optional[datetime] = None
