"""Platform-admin authentication -- deliberately self-contained and
independent from the customer-facing auth in app/core/security.py. Uses
its own JWT signing, its own token payload shape ({"admin_id": ...}, no
company_id at all since PlatformAdmin isn't tenant-scoped), and its own
password hashing. This is intentional: the whole point of this system is
that it must never accidentally inherit any customer-tenant assumption
from the regular auth path.
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.core.models.company import PlatformAdmin

# Separate secret from the customer-facing JWT secret, if one is
# configured -- falls back to a hardcoded dev-only default if NEITHER
# ADMIN_JWT_SECRET nor JWT_SECRET exist on settings, so this module never
# hard-crashes on import from an unverified config attribute name. CHANGE
# THIS in production by setting ADMIN_JWT_SECRET explicitly in your env.
_fallback_secret = getattr(settings, "JWT_SECRET", None) or "change-me-admin-secret-dev-only"
ADMIN_JWT_SECRET = getattr(settings, "ADMIN_JWT_SECRET", None) or f"{_fallback_secret}:admin"
ADMIN_JWT_ALGORITHM = "HS256"
ADMIN_TOKEN_EXPIRE_MINUTES = 60 * 12  # 12h -- admin sessions, not long-lived like customer refresh tokens

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
admin_bearer_scheme = HTTPBearer(auto_error=True)


def hash_admin_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_admin_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_admin_token(admin_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ADMIN_TOKEN_EXPIRE_MINUTES)
    payload = {"admin_id": admin_id, "type": "platform_admin", "exp": expire}
    return jwt.encode(payload, ADMIN_JWT_SECRET, algorithm=ADMIN_JWT_ALGORITHM)


def decode_admin_token(token: str) -> dict:
    payload = jwt.decode(token, ADMIN_JWT_SECRET, algorithms=[ADMIN_JWT_ALGORITHM])
    if payload.get("type") != "platform_admin":
        raise JWTError("Not an admin token")
    return payload


async def get_current_admin(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(admin_bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlatformAdmin:
    try:
        payload = decode_admin_token(credentials.credentials)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired admin token")

    admin = await db.get(PlatformAdmin, int(payload["admin_id"]))
    if admin is None or not admin.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin not found or deactivated")
    return admin


CurrentAdmin = Annotated[PlatformAdmin, Depends(get_current_admin)]