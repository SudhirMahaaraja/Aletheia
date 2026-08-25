from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class GraphNodeInDB(BaseModel):
    id: str  # deterministic: "{type}_{sha256[:16]}"
    type: str  # "Function" | "Class" | "File" | "Project" | "Concept" | "Document" | "Section" | "DesignSystem"
    name: str
    repo_name: Optional[str] = None
    file_path: Optional[str] = None
    language: Optional[str] = None
    summary: Optional[str] = None
    metadata: dict = {}
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class GraphEdgeInDB(BaseModel):
    id: str = ""
    from_id: str
    to_id: str
    type: str  # "IMPORTS" | "CALLS" | "DEFINES" | "IMPLEMENTS" | "SIMILAR_TO" | "REFERENCES" | "BELONGS_TO" | "PART_OF" | "DESCRIBES"
    weight: Optional[float] = None
    created_at: Optional[datetime] = None
