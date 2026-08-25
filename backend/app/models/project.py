from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ProjectInDB(BaseModel):
    id: str = ""
    name: str
    client: str = ""
    description: str = ""
    status: str = "active"  # "active" | "completed" | "archived"
    tags: list[str] = []
    created_at: Optional[datetime] = None
    created_by: str = ""
