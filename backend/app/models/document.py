from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DocumentInDB(BaseModel):
    id: str = ""
    title: str
    original_filename: str
    file_type: str  # "pdf" | "docx" | "md" | "txt"
    project_id: Optional[str] = None
    uploaded_by: str = ""
    uploaded_at: Optional[datetime] = None
    ingestion_status: str = "queued"  # "queued" | "running" | "done" | "failed"
    total_chunks: int = 0
    file_size_bytes: int = 0
