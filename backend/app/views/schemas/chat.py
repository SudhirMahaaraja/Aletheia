from typing import Optional

from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    mode: str  # "vault" | "repo" | "brainstorm"
    selected_repos: Optional[list[str]] = None


class SessionResponse(BaseModel):
    session_id: str
    mode: str
    created_at: str


class SendMessageRequest(BaseModel):
    content: str


class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    sources: list[dict] = []
    generated_doc: Optional[dict] = None
    created_at: str
    token_count: Optional[int] = None
