import logging
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse, FileResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

from app.core.dependencies import get_current_user
from app.db.mongodb import get_db
from app.models.user import UserInDB
from app.views.schemas.chat import (
    CreateSessionRequest,
    SendMessageRequest,
    SessionResponse,
    MessageResponse,
)
from app.controllers.rag.vault_chat import VaultChatService
from app.controllers.rag.repo_chat import RepoChatService
from app.controllers.rag.brainstorm import BrainstormService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: CreateSessionRequest,
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Creates a new chat session for the current user.
    """
    valid_modes = {"vault", "repo", "brainstorm"}
    if payload.mode not in valid_modes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid chat mode. Must be one of: {', '.join(valid_modes)}",
        )

    now = datetime.now(timezone.utc)
    session_id = str(ObjectId())
    
    session_doc = {
        "_id": session_id,
        "user_id": current_user.id,
        "mode": payload.mode,
        "title": f"New {payload.mode.capitalize()} Session",
        "selected_repos": payload.selected_repos or [],
        "message_count": 0,
        "context_summary": "",
        "created_at": now,
        "updated_at": now,
    }

    try:
        await db.chat_sessions.insert_one(session_doc)
    except Exception as exc:
        logger.error("Failed to create chat session: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create session",
        )

    return SessionResponse(
        session_id=session_id,
        mode=payload.mode,
        created_at=now.isoformat() + "Z",
    )


@router.get("/sessions", response_model=List[dict])
async def list_sessions(
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Lists all chat sessions belonging to the current user.
    """
    query = {}
    if current_user.role not in ("admin", "superadmin"):
        query["user_id"] = current_user.id
    cursor = db.chat_sessions.find(query).sort("updated_at", -1)
    sessions = await cursor.to_list(length=100)
    
    result = []
    for s in sessions:
        created_at_val = s.get("created_at")
        updated_at_val = s.get("updated_at")
        
        created_at_str = ""
        if isinstance(created_at_val, datetime):
            created_at_str = created_at_val.isoformat() + "Z"
        elif created_at_val:
            created_at_str = str(created_at_val)
            
        updated_at_str = ""
        if isinstance(updated_at_val, datetime):
            updated_at_str = updated_at_val.isoformat() + "Z"
        elif updated_at_val:
            updated_at_str = str(updated_at_val)

        result.append({
            "session_id": str(s["_id"]),
            "mode": s.get("mode", "vault"),
            "title": s.get("title", ""),
            "selected_repos": s.get("selected_repos", []),
            "message_count": s.get("message_count", 0),
            "created_at": created_at_str,
            "updated_at": updated_at_str,
        })
    return result


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Deletes a chat session and all its associated messages.
    """
    query = {"_id": session_id}
    if current_user.role not in ("admin", "superadmin"):
        query["user_id"] = current_user.id
        
    session_doc = await db.chat_sessions.find_one(query)
    if not session_doc and ObjectId.is_valid(session_id):
        query_oid = {"_id": ObjectId(session_id)}
        if current_user.role not in ("admin", "superadmin"):
            query_oid["user_id"] = current_user.id
        session_doc = await db.chat_sessions.find_one(query_oid)

    if not session_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )

    try:
        # Delete session
        await db.chat_sessions.delete_one({"_id": session_doc["_id"]})
        # Delete messages associated with this session
        await db.chat_messages.delete_many({"session_id": session_id})
    except Exception as exc:
        logger.error("Failed to delete session: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete session",
        )


@router.get("/sessions/{session_id}/messages", response_model=List[MessageResponse])
async def list_messages(
    session_id: str,
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Lists all messages within a given chat session.
    """
    query = {"_id": session_id}
    if current_user.role not in ("admin", "superadmin"):
        query["user_id"] = current_user.id
        
    session_doc = await db.chat_sessions.find_one(query)
    if not session_doc and ObjectId.is_valid(session_id):
        query_oid = {"_id": ObjectId(session_id)}
        if current_user.role not in ("admin", "superadmin"):
            query_oid["user_id"] = current_user.id
        session_doc = await db.chat_sessions.find_one(query_oid)

    if not session_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found or access denied",
        )

    cursor = db.chat_messages.find({"session_id": session_id}).sort("created_at", 1)
    messages = await cursor.to_list(length=200)

    result = []
    for m in messages:
        sources = m.get("sources", [])
        resolved_sources = []
        for src in sources:
            src_copy = dict(src)
            if not src_copy.get("node_id"):
                node_id = None
                repo_name = src_copy.get("repo_name")
                file_path = src_copy.get("file_path")
                name = src_copy.get("name")
                chunk_id = src_copy.get("chunk_id")
                
                if repo_name:
                    node = None
                    if file_path and name:
                        node = await db.graph_nodes.find_one({
                            "repo_name": repo_name,
                            "file_path": file_path,
                            "name": name
                        })
                    if not node and file_path:
                        node = await db.graph_nodes.find_one({
                            "repo_name": repo_name,
                            "file_path": file_path,
                            "type": "File"
                        })
                    if not node:
                        node = await db.graph_nodes.find_one({
                            "repo_name": repo_name,
                            "type": "Repository"
                        })
                    if node:
                        node_id = str(node["_id"])
                elif chunk_id:
                    node_id = chunk_id
                elif src_copy.get("document_id"):
                    node_id = src_copy.get("document_id")
                
                src_copy["node_id"] = node_id
            
            # Stringify any ObjectId fields to prevent Pydantic/JSON serialization errors
            if "chunk_id" in src_copy and src_copy["chunk_id"] is not None:
                src_copy["chunk_id"] = str(src_copy["chunk_id"])
            if "document_id" in src_copy and src_copy["document_id"] is not None:
                src_copy["document_id"] = str(src_copy["document_id"])
            if "node_id" in src_copy and src_copy["node_id"] is not None:
                src_copy["node_id"] = str(src_copy["node_id"])

            resolved_sources.append(src_copy)

        result.append(MessageResponse(
            id=str(m["_id"]),
            session_id=m["session_id"],
            role=m["role"],
            content=m["content"],
            sources=resolved_sources,
            generated_doc=m.get("generated_doc"),
            created_at=m["created_at"].isoformat() + "Z" if isinstance(m["created_at"], datetime) else str(m["created_at"]),
        ))
    return result


@router.post("/sessions/{session_id}/message")
async def send_message(
    session_id: str,
    payload: SendMessageRequest,
    request: Request,
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Sends a message to a session and streams back the assistant response.
    """
    query = {"_id": session_id}
    if current_user.role not in ("admin", "superadmin"):
        query["user_id"] = current_user.id
        
    session_doc = await db.chat_sessions.find_one(query)
    if not session_doc and ObjectId.is_valid(session_id):
        query_oid = {"_id": ObjectId(session_id)}
        if current_user.role not in ("admin", "superadmin"):
            query_oid["user_id"] = current_user.id
        session_doc = await db.chat_sessions.find_one(query_oid)

    if not session_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found or access denied",
        )

    # Fetch recent messages for history/context
    cursor = db.chat_messages.find({"session_id": session_id}).sort("created_at", 1)
    all_msgs = await cursor.to_list(length=100)
    chat_history = [{"role": m["role"], "content": m["content"]} for m in all_msgs]

    mode = session_doc.get("mode", "vault")
    selected_repos = session_doc.get("selected_repos", [])
    ip_address = request.client.host if request.client else ""

    # Route message to the appropriate service
    if mode == "vault":
        stream_gen = VaultChatService.stream_response(
            db=db,
            session_id=session_id,
            user_id=current_user.id,
            question=payload.content,
            chat_history=chat_history,
            ip_address=ip_address,
        )
    elif mode == "repo":
        stream_gen = RepoChatService.stream_response(
            db=db,
            session_id=session_id,
            user_id=current_user.id,
            question=payload.content,
            chat_history=chat_history,
            selected_repos=selected_repos,
            ip_address=ip_address,
        )
    elif mode == "brainstorm":
        stream_gen = BrainstormService.stream_response(
            db=db,
            session_id=session_id,
            user_id=current_user.id,
            question=payload.content,
            chat_history=chat_history,
            selected_repos=selected_repos,
            ip_address=ip_address,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown chat mode: {mode}",
        )

    # Set title of session if it is a new session
    if session_doc.get("message_count", 0) == 0:
        # Dynamically title the session based on the first question
        title = payload.content[:30] + ("..." if len(payload.content) > 30 else "")
        try:
            await db.chat_sessions.update_one({"_id": session_doc["_id"]}, {"$set": {"title": title}})
        except Exception:
            pass

    return StreamingResponse(
        stream_gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
        },
    )


@router.get("/download/{filename}")
async def download_document(
    filename: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Downloads a brainstorm generated report/document (.docx) from vault/generated/.
    """
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    from app.core.config import get_settings
    from app.controllers.vault_manager import resolve_vault_dir
    
    settings = get_settings()
    vault_dir = resolve_vault_dir(settings.VAULT_PATH)
    file_path = vault_dir / "generated" / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
        
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
