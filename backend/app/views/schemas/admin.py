from typing import Optional

from pydantic import BaseModel


class UpdateRoleRequest(BaseModel):
    role: str  # "admin" | "developer" | "pm"


class StatsResponse(BaseModel):
    total_users: int
    total_repos: int
    total_documents: int
    total_chunks_code: int
    total_chunks_docs: int
    total_graph_nodes: int
    total_graph_edges: int
    active_jobs: int


class AuditLogResponse(BaseModel):
    id: str
    user_id: str
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    detail: Optional[str] = None
    ip_address: str = ""
    created_at: Optional[str] = None
