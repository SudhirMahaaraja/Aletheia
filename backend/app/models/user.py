from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserRole(str, Enum):
    admin = "admin"
    developer = "developer"
    pm = "pm"


class UserInDB(BaseModel):
    id: str = ""
    email: EmailStr
    hashed_password: str
    full_name: str
    role: str = UserRole.developer.value
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"populate_by_name": True}
