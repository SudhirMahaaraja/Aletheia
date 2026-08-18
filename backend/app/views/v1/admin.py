import logging
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

from app.core.dependencies import require_admin
from app.db.mongodb import get_db
from app.models.user import UserInDB
from app.views.schemas.admin import UpdateRoleRequest, StatsResponse, AuditLogResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=List[dict])
async def list_users(
    db: AsyncIOMotorDatabase = Depends(get_db),
    admin: UserInDB = Depends(require_admin),
):
    """
    Get all registered users. Requires admin privilege.
    """
    cursor = db.users.find({}).sort("created_at", -1)
    users = await cursor.to_list(length=200)
    
    result = []
    for u in users:
        result.append({
            "id": str(u["_id"]),
            "email": u["email"],
            "full_name": u.get("full_name", ""),
            "role": u.get("role", "developer"),
            "is_active": u.get("is_active", True),
            "created_at": u["created_at"].isoformat() + "Z" if isinstance(u.get("created_at"), datetime) else str(u.get("created_at")),
            "updated_at": u["updated_at"].isoformat() + "Z" if isinstance(u.get("updated_at"), datetime) else str(u.get("updated_at")),
        })
    return result


@router.patch("/users/{user_id}/role", response_model=dict)
async def update_user_role(
    user_id: str,
    payload: UpdateRoleRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    admin: UserInDB = Depends(require_admin),
):
    """
    Update a user's role. Requires admin privilege.
    """
    valid_roles = {"admin", "developer", "pm"}
    if payload.role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}",
        )

    try:
        user_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        user_doc = await db.users.find_one({"_id": user_oid})
    except Exception:
        user_doc = await db.users.find_one({"_id": user_id})

    if not user_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Perform update
    now = datetime.now(timezone.utc)
    try:
        if isinstance(user_doc["_id"], ObjectId):
            await db.users.update_one({"_id": user_doc["_id"]}, {"$set": {"role": payload.role, "updated_at": now}})
        else:
            await db.users.update_one({"_id": user_id}, {"$set": {"role": payload.role, "updated_at": now}})
            
        # Write audit log
        await db.audit_logs.insert_one({
            "user_id": admin.id,
            "action": "user_role_change",
            "resource_type": "user",
            "resource_id": user_id,
            "detail": f"Changed user {user_doc['email']} role to {payload.role}",
            "ip_address": "",
            "created_at": now,
        })
    except Exception as exc:
        logger.error("Failed to update user role: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update role",
        )

    return {"message": "Role updated successfully", "user_id": user_id, "role": payload.role}


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    admin: UserInDB = Depends(require_admin),
):
    """
    Delete a user. Requires admin privilege.
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own admin account",
        )

    try:
        user_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        user_doc = await db.users.find_one({"_id": user_oid})
    except Exception:
        user_doc = await db.users.find_one({"_id": user_id})

    if not user_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    try:
        if isinstance(user_doc["_id"], ObjectId):
            await db.users.delete_one({"_id": user_doc["_id"]})
        else:
            await db.users.delete_one({"_id": user_id})
            
        # Write audit log
        await db.audit_logs.insert_one({
            "user_id": admin.id,
            "action": "user_delete",
            "resource_type": "user",
            "resource_id": user_id,
            "detail": f"Deleted user account {user_doc['email']}",
            "ip_address": "",
            "created_at": datetime.now(timezone.utc),
        })
    except Exception as exc:
        logger.error("Failed to delete user: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete user",
        )


@router.get("/audit-logs", response_model=List[AuditLogResponse])
async def list_audit_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncIOMotorDatabase = Depends(get_db),
    admin: UserInDB = Depends(require_admin),
):
    """
    Get system audit logs. Requires admin privilege.
    """
    cursor = db.audit_logs.find({}).sort("created_at", -1).skip(skip).limit(limit)
    logs = await cursor.to_list(length=limit)

    result = []
    for l in logs:
        result.append(AuditLogResponse(
            id=str(l["_id"]),
            user_id=l.get("user_id", ""),
            action=l.get("action", ""),
            resource_type=l.get("resource_type", ""),
            resource_id=l.get("resource_id"),
            detail=l.get("detail"),
            ip_address=l.get("ip_address", ""),
            created_at=l["created_at"].isoformat() + "Z" if isinstance(l.get("created_at"), datetime) else str(l.get("created_at")),
        ))
    return result


@router.get("/stats", response_model=StatsResponse)
async def get_system_stats(
    db: AsyncIOMotorDatabase = Depends(get_db),
    admin: UserInDB = Depends(require_admin),
):
    """
    Get system usage and ingestion statistics. Requires admin privilege.
    """
    total_users = await db.users.count_documents({})
    total_repos = await db.repositories.count_documents({})
    total_documents = await db.documents.count_documents({})
    total_chunks_code = await db.code_chunks.count_documents({})
    total_chunks_docs = await db.document_chunks.count_documents({})
    total_graph_nodes = await db.graph_nodes.count_documents({})
    total_graph_edges = await db.graph_edges.count_documents({})
    
    # Active jobs: any job that is not completed or failed
    active_jobs = await db.ingestion_jobs.count_documents({
        "status": {"$in": ["queued", "processing", "pending"]}
    })

    return StatsResponse(
        total_users=total_users,
        total_repos=total_repos,
        total_documents=total_documents,
        total_chunks_code=total_chunks_code,
        total_chunks_docs=total_chunks_docs,
        total_graph_nodes=total_graph_nodes,
        total_graph_edges=total_graph_edges,
        active_jobs=active_jobs,
    )
