import re
import secrets
import string

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.core.models.company import Company, CompanyInvite
from app.core.models.organization import Organization
from app.core.models.user import User
from app.core.schemas.auth import AcceptInviteRequest, CompanyRegisterRequest, LoginRequest, TokenPair

SHORT_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
SHORT_CODE_LENGTH = 6


def _slugify_company_name(name: str) -> str:
    match = re.search(r"[A-Za-z0-9]+", name)
    word = match.group(0) if match else "COMPANY"
    return word.upper()[:20]


def _generate_short_code(company_name: str) -> str:
    prefix = _slugify_company_name(company_name)
    suffix = "".join(secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH))
    return f"{prefix}-{suffix}"


async def _unique_short_code(db: AsyncSession, company_name: str) -> str:
    for _ in range(10):
        candidate = _generate_short_code(company_name)
        existing = await db.execute(select(CompanyInvite).where(CompanyInvite.short_code == candidate))
        if existing.scalar_one_or_none() is None:
            return candidate
    raise HTTPException(status_code=500, detail="Could not generate a unique invite code, please try again")


async def register_company(db: AsyncSession, data: CompanyRegisterRequest) -> TokenPair:
    """Registers the Organization and its owner_admin User only.

    Deliberately does NOT create a Company anymore -- that used to happen
    automatically here (named after the org, or data.company_name if
    given), but the owner wants to create their own Company explicitly
    afterward via POST /organizations/{organization_id}/companies. The
    owner_admin User is created with company_id=None, which is now a
    valid, supported state (see User.company_id in
    app/core/models/user.py) rather than a transient/broken one.

    data.company_name / data.timezone are accepted but unused here --
    kept on the request schema for backward compatibility with any
    frontend still sending them, rather than breaking that request
    outright. They can be dropped from CompanyRegisterRequest once the
    frontend registration form stops sending them.
    """
    existing = await db.execute(select(User).where(User.email == data.owner_email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    organization = Organization(name=data.organization_name)
    db.add(organization)
    await db.flush()

    owner = User(
        company_id=None,
        organization_id=organization.id,
        email=data.owner_email,
        password_hash=hash_password(data.owner_password),
        role="owner_admin",
        full_name=data.owner_full_name,
    )
    db.add(owner)
    await db.flush()

    organization.owner_user_id = owner.id
    await db.flush()
    return _token_pair(owner)


async def login(db: AsyncSession, data: LoginRequest) -> TokenPair:
    res = await db.execute(select(User).where(User.email == data.email, User.active.is_(True)))
    user = res.scalar_one_or_none()
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return _token_pair(user)


async def accept_invite(db: AsyncSession, data: AcceptInviteRequest) -> TokenPair:
    submitted = data.token.strip()
    res = await db.execute(select(CompanyInvite).where(
        (CompanyInvite.token == submitted) | (CompanyInvite.short_code == submitted.upper())
    ))
    invite = res.scalar_one_or_none()
    if invite is None or invite.accepted_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or already-used invite")

    from sqlalchemy import func
    existing = await db.execute(select(User).where(User.email == invite.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    invite_company = await db.get(Company, invite.company_id)

    user = User(
        company_id=invite.company_id,
        organization_id=invite_company.organization_id,
        email=invite.email,
        password_hash=hash_password(data.password),
        role=invite.role,
        team_id=invite.team_id,
        full_name=data.full_name,
        timezone=invite.timezone,
        holiday_country=invite.holiday_country,
        job_type=invite.job_type,
        actual_working_hours=invite.actual_working_hours,
        hourly_fee=invite.hourly_fee,
        language=invite.language,
    )
    invite.accepted_at = func.now()
    db.add(user)
    await db.flush()
    return _token_pair(user)


async def make_invite(db: AsyncSession, company_id: int, email: str, role: str, team_id: int | None,
                      timezone: str | None = None, holiday_country: str | None = None,
                      job_type: str = "full_time", actual_working_hours: bool = True,
                      hourly_fee: float | None = None, language: str = "en") -> CompanyInvite:
    company = await db.get(Company, company_id)
    short_code = await _unique_short_code(db, company.name if company else "COMPANY")
    return CompanyInvite(
        company_id=company_id, email=email, role=role, team_id=team_id,
        timezone=timezone, holiday_country=holiday_country,
        job_type=job_type, actual_working_hours=actual_working_hours, hourly_fee=hourly_fee,
        language=language,
        token=secrets.token_urlsafe(32),
        short_code=short_code,
    )


def refresh_tokens(user: User) -> TokenPair:
    return _token_pair(user)


def _token_pair(user: User) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user.id, user.company_id, user.organization_id, user.role),
        refresh_token=create_refresh_token(user.id, user.company_id, user.organization_id, user.role),
    )