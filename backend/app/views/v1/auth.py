import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.dependencies import get_current_user, require_admin
from app.db.mongodb import get_db
from app.models.user import UserInDB
from app.views.schemas.auth import (
    LoginResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.controllers import auth_controller

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse)
async def register(
    body: RegisterRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(require_admin),
) -> UserResponse:
    user = await auth_controller.register_user(
        db=db,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        role=body.role,
    )
    return UserResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> LoginResponse:
    ip_address = request.client.host if request.client else ""
    access_token, refresh_token = await auth_controller.login_user(
        db=db,
        email=form_data.username,
        password=form_data.password,
        ip_address=ip_address,
    )
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> TokenResponse:
    access_token, refresh_token = await auth_controller.refresh_access_token(
        db=db,
        refresh_token=body.refresh_token,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/logout")
async def logout(
    body: RefreshRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user),
) -> dict:
    await auth_controller.revoke_refresh_token(db=db, refresh_token=body.refresh_token)
    return {"message": "logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: UserInDB = Depends(get_current_user),
) -> UserResponse:
    return UserResponse(
        user_id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        is_active=current_user.is_active,
        created_at=current_user.created_at.isoformat() if current_user.created_at else None,
    )
