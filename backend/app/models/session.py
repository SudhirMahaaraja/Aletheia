from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ChatSessionInDB(BaseModel):
    id: str = ""
    user_id: str
    mode: str  # "vault" | "repo" | "brainstorm"
    title: str = ""
    selected_repos: list[str] = []
    message_count: int = 0
    context_summary: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ChatMessageInDB(BaseModel):
    id: str = ""
    session_id: str
    role: str  # "user" | "assistant"
    content: str
    sources: list[dict] = []
    created_at: Optional[datetime] = None
    token_count: Optional[int] = None
