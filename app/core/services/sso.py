"""SSO handoff: Core Dashboard -> a module's own frontend.

Deliberately minimal, matching the agreed spec exactly: the code
identifies WHO (a user_id), nothing about which module or company --
the target module is whichever frontend the code gets redirected to
(e.g. https://hr.ants.com?code=...), and that module's own
require_module_enabled() dependency is what actually gates access once
the person is logged in there. No module_key is stored on the code
itself; adding one would duplicate a check that already happens
correctly downstream.
"""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.sso import SsoCode
from app.core.models.user import User
from app.core.schemas.auth import TokenPair
from app.core.services.auth import refresh_tokens

CODE_TTL_SECONDS = 30


async def issue_code(db: AsyncSession, user: User) -> tuple[str, int]:
    code = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=CODE_TTL_SECONDS)
    db.add(SsoCode(code=code, user_id=user.id, expires_at=expires_at))
    await db.flush()
    return code, CODE_TTL_SECONDS


async def consume_code(db: AsyncSession, code: str) -> TokenPair:
    res = await db.execute(select(SsoCode).where(SsoCode.code == code))
    sso_code = res.scalar_one_or_none()

    # Same generic message for "doesn't exist" / "expired" / "already used"
    # -- distinguishing them for the caller isn't useful (all three mean
    # "go back to Core Dashboard and click Enter again") and would leak
    # whether a guessed code was ever real.
    invalid = HTTPException(status_code=400, detail="Invalid or expired code")
    if sso_code is None:
        raise invalid
    if sso_code.used_at is not None:
        raise invalid
    if sso_code.expires_at < datetime.now(timezone.utc):
        raise invalid

    sso_code.used_at = datetime.now(timezone.utc)
    await db.flush()

    user = await db.get(User, sso_code.user_id)
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")

    return refresh_tokens(user)