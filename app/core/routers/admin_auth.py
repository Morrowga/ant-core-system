"""Platform-admin login -- separate from /auth (customer login). No
registration endpoint here deliberately: admin accounts are created
directly in the database by you, not self-service signup."""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.admin_auth import CurrentAdmin, create_admin_token, verify_admin_password
from app.core.dependencies import DB
from app.core.models.company import PlatformAdmin

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


@router.post("/login")
async def admin_login(payload: dict, db: DB):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    admin = (await db.execute(
        select(PlatformAdmin).where(PlatformAdmin.email == email)
    )).scalar_one_or_none()

    if admin is None or not admin.active or not verify_admin_password(password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_admin_token(admin.id)
    return {"access_token": token, "token_type": "bearer",
            "admin": {"id": admin.id, "email": admin.email, "full_name": admin.full_name}}


@router.get("/me")
async def admin_me(admin: CurrentAdmin):
    """Lets the frontend restore the logged-in admin's info after a page
    reload, without needing a full session-restore/refresh-token flow --
    the token itself already persists in localStorage across reloads,
    this just re-fetches who it belongs to."""
    return {"id": admin.id, "email": admin.email, "full_name": admin.full_name}