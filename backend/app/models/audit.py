from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AuditLogInDB(BaseModel):
    id: str = ""
    user_id: str
    action: str  # "login" | "chat_message" | "ingest_start" | "document_upload" | "repo_select" | "user_role_change"
    resource_type: str  # "session" | "repository" | "document" | "user"
    resource_id: Optional[str] = None
    detail: Optional[str] = None
    ip_address: str = ""
    created_at: Optional[datetime] = None
