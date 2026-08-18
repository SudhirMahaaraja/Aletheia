from typing import Optional

from pydantic import BaseModel


class IngestRepoRequest(BaseModel):
    repo_full_name: str


class IngestJobResponse(BaseModel):
    job_id: str
    status: str


class IngestDocumentResponse(BaseModel):
    job_id: str
    document_id: str
    status: str


class JobDetailResponse(BaseModel):
    job_id: str
    job_type: str
    source_id: str
    source_name: str
    status: str
    files_total: int = 0
    files_processed: int = 0
    chunks_created: int = 0
    nodes_created: int = 0
    edges_created: int = 0
    errors: list[str] = []
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    triggered_by: str = ""
    current_file: Optional[str] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: str


class CreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None
