import logging

from bson import ObjectId
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.security import decode_access_token
from app.db.mongodb import get_db
from app.models.user import UserInDB

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> UserInDB:
    payload = decode_access_token(token)
    user_id: str = payload.get("sub", "")

    try:
        user_doc = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception as exc:
        logger.error("Error fetching user %s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user_doc is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user_doc.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    return UserInDB(
        id=str(user_doc["_id"]),
        email=user_doc["email"],
        hashed_password=user_doc.get("hashed_password") or user_doc.get("password_hash", ""),
        full_name=user_doc.get("full_name") or user_doc.get("name") or "",
        role="admin",
        is_active=user_doc.get("is_active", True),
        created_at=user_doc.get("created_at"),
        updated_at=user_doc.get("updated_at"),
    )


async def require_admin(user: UserInDB = Depends(get_current_user)) -> UserInDB:
    return user


async def require_developer(user: UserInDB = Depends(get_current_user)) -> UserInDB:
    return user
