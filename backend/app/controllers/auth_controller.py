import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
    verify_refresh_token,
)
from app.models.user import UserInDB

logger = logging.getLogger(__name__)


async def register_user(
    db: AsyncIOMotorDatabase,
    email: str,
    password: str,
    full_name: str,
    role: str,
) -> UserInDB:
    existing = await db.users.find_one({"email": email.lower().strip()})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists",
        )

    valid_roles = {"admin", "developer", "pm"}
    if role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}",
        )

    now = datetime.now(timezone.utc)
    user_doc = {
        "email": email.lower().strip(),
        "hashed_password": hash_password(password),
        "full_name": full_name.strip(),
        "role": role,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }

    try:
        result = await db.users.insert_one(user_doc)
    except Exception as exc:
        logger.error("Failed to insert user: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user",
        )

    return UserInDB(
        id=str(result.inserted_id),
        email=user_doc["email"],
        hashed_password=user_doc["hashed_password"],
        full_name=user_doc["full_name"],
        role=user_doc["role"],
        is_active=user_doc["is_active"],
        created_at=user_doc["created_at"],
        updated_at=user_doc["updated_at"],
    )


async def login_user(
    db: AsyncIOMotorDatabase,
    email: str,
    password: str,
    ip_address: str = "",
) -> tuple[str, str]:
    user_doc = await db.users.find_one({"email": email.lower().strip()})
    if user_doc is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user_doc.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    hashed_pwd = user_doc.get("hashed_password") or user_doc.get("password_hash")
    if not hashed_pwd or not verify_password(password, hashed_pwd):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    user_id = str(user_doc["_id"])
    access_token = create_access_token({"sub": user_id, "role": user_doc["role"]})
    raw_refresh = create_refresh_token()

    settings = get_settings()
    now = datetime.now(timezone.utc)
    refresh_doc = {
        "user_id": user_id,
        "hashed_token": hash_refresh_token(raw_refresh),
        "expires_at": now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        "created_at": now,
        "revoked": False,
    }

    try:
        await db.refresh_tokens.insert_one(refresh_doc)
    except Exception as exc:
        logger.error("Failed to store refresh token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed",
        )

    # Audit log
    try:
        await db.audit_logs.insert_one({
            "user_id": user_id,
            "action": "login",
            "resource_type": "user",
            "resource_id": user_id,
            "detail": f"User {user_doc['email']} logged in",
            "ip_address": ip_address,
            "created_at": now,
        })
    except Exception as exc:
        logger.warning("Failed to write audit log: %s", exc)

    return access_token, raw_refresh


async def refresh_access_token(
    db: AsyncIOMotorDatabase,
    refresh_token: str,
) -> tuple[str, str]:
    now = datetime.now(timezone.utc)

    # Find all non-revoked, non-expired refresh tokens
    cursor = db.refresh_tokens.find({
        "revoked": False,
        "expires_at": {"$gt": now},
    })
    token_docs = await cursor.to_list(length=500)

    matched_doc = None
    for doc in token_docs:
        if verify_refresh_token(refresh_token, doc["hashed_token"]):
            matched_doc = doc
            break

    if matched_doc is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user_id = matched_doc["user_id"]

    # Revoke old token
    try:
        await db.refresh_tokens.update_one(
            {"_id": matched_doc["_id"]},
            {"$set": {"revoked": True}},
        )
    except Exception as exc:
        logger.error("Failed to revoke old refresh token: %s", exc)

    # Look up the user to get their current role
    user_doc = await db.users.find_one({"_id": ObjectId(user_id)})
    if user_doc is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Issue new tokens
    new_access = create_access_token({"sub": user_id, "role": user_doc["role"]})
    new_raw_refresh = create_refresh_token()

    settings = get_settings()
    new_refresh_doc = {
        "user_id": user_id,
        "hashed_token": hash_refresh_token(new_raw_refresh),
        "expires_at": now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        "created_at": now,
        "revoked": False,
    }

    try:
        await db.refresh_tokens.insert_one(new_refresh_doc)
    except Exception as exc:
        logger.error("Failed to store new refresh token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token refresh failed",
        )

    return new_access, new_raw_refresh


async def revoke_refresh_token(
    db: AsyncIOMotorDatabase,
    refresh_token: str,
) -> None:
    now = datetime.now(timezone.utc)
    cursor = db.refresh_tokens.find({
        "revoked": False,
        "expires_at": {"$gt": now},
    })
    token_docs = await cursor.to_list(length=500)

    for doc in token_docs:
        if verify_refresh_token(refresh_token, doc["hashed_token"]):
            try:
                await db.refresh_tokens.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"revoked": True}},
                )
            except Exception as exc:
                logger.error("Failed to revoke refresh token: %s", exc)
            return

    logger.warning("Attempted to revoke a token that was not found")


async def get_user_by_id(
    db: AsyncIOMotorDatabase,
    user_id: str,
) -> Optional[UserInDB]:
    try:
        user_doc = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        return None

    if user_doc is None:
        return None

    return UserInDB(
        id=str(user_doc["_id"]),
        email=user_doc["email"],
        hashed_password=user_doc.get("hashed_password") or user_doc.get("password_hash", ""),
        full_name=user_doc.get("full_name") or user_doc.get("name") or "",
        role=user_doc.get("role", "developer"),
        is_active=user_doc.get("is_active", True),
        created_at=user_doc.get("created_at"),
        updated_at=user_doc.get("updated_at"),
    )


async def get_user_by_email(
    db: AsyncIOMotorDatabase,
    email: str,
) -> Optional[UserInDB]:
    user_doc = await db.users.find_one({"email": email.lower().strip()})
    if user_doc is None:
        return None

    return UserInDB(
        id=str(user_doc["_id"]),
        email=user_doc["email"],
        hashed_password=user_doc.get("hashed_password") or user_doc.get("password_hash", ""),
        full_name=user_doc.get("full_name") or user_doc.get("name") or "",
        role=user_doc.get("role", "developer"),
        is_active=user_doc.get("is_active", True),
        created_at=user_doc.get("created_at"),
        updated_at=user_doc.get("updated_at"),
    )


async def ensure_admin_exists(db: AsyncIOMotorDatabase) -> None:
    admin_doc = await db.users.find_one({"role": "admin"})
    if admin_doc is None:
        logger.info("No admin user found -- creating default admin account")
        await register_user(
            db=db,
            email="admin@bws.com",
            password="admin123",
            full_name="Admin",
            role="admin",
        )
        logger.info("Default admin created: admin@bws.com / admin123")
