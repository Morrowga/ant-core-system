from fastapi import APIRouter, HTTPException
from jose import JWTError

from app.core.dependencies import DB, CurrentUser
from app.core.security import decode_token, hash_password, verify_password
from app.schemas.auth import (AcceptInviteRequest, ChangePasswordRequest, CompanyRegisterRequest,
                              LoginRequest, RefreshRequest, TokenPair)
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenPair, status_code=201)
async def register(data: CompanyRegisterRequest, db: DB):
    return await auth_service.register_company(db, data)


@router.post("/login", response_model=TokenPair)
async def login(data: LoginRequest, db: DB):
    return await auth_service.login(db, data)


@router.post("/refresh", response_model=TokenPair)
async def refresh(data: RefreshRequest, db: DB):
    from app.models.users import User
    try:
        payload = decode_token(data.refresh_token, expected_type="refresh")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")
    return auth_service.refresh_tokens(user)


@router.post("/logout", status_code=204)
async def logout(user: CurrentUser):
    # Stateless JWTs: client discards tokens. Hook for a Redis denylist if needed.
    return None


@router.post("/accept-invite", response_model=TokenPair, status_code=201)
async def accept_invite(data: AcceptInviteRequest, db: DB):
    return await auth_service.accept_invite(db, data)


@router.post("/me/change-password", status_code=204)
async def change_password(data: ChangePasswordRequest, user: CurrentUser, db: DB):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password incorrect")
    user.password_hash = hash_password(data.new_password)
    await db.flush()
    return None