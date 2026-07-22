import secrets

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.models.company import Company, CompanyInvite, Subscription
from app.models.users import User
from app.schemas.auth import AcceptInviteRequest, CompanyRegisterRequest, LoginRequest, TokenPair


async def register_company(db: AsyncSession, data: CompanyRegisterRequest) -> TokenPair:
    existing = await db.execute(select(User).where(User.email == data.owner_email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    company = Company(name=data.company_name, timezone=data.timezone)
    db.add(company)
    await db.flush()  # get company.id

    owner = User(
        company_id=company.id,
        email=data.owner_email,
        password_hash=hash_password(data.owner_password),
        role="owner_admin",
        full_name=data.owner_full_name,
    )
    db.add(owner)
    db.add(Subscription(company_id=company.id, plan_tier="startup", status="incomplete", seats_used=1))
    await db.flush()
    return _token_pair(owner)


async def login(db: AsyncSession, data: LoginRequest) -> TokenPair:
    res = await db.execute(select(User).where(User.email == data.email, User.active.is_(True)))
    user = res.scalar_one_or_none()
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return _token_pair(user)


async def accept_invite(db: AsyncSession, data: AcceptInviteRequest) -> TokenPair:
    res = await db.execute(select(CompanyInvite).where(CompanyInvite.token == data.token))
    invite = res.scalar_one_or_none()
    if invite is None or invite.accepted_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or already-used invite")

    from sqlalchemy import func
    existing = await db.execute(select(User).where(User.email == invite.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        company_id=invite.company_id,
        email=invite.email,
        password_hash=hash_password(data.password),
        role=invite.role,
        team_id=invite.team_id,
        full_name=data.full_name,
        timezone=invite.timezone,
        holiday_country=invite.holiday_country,
        # New: transferred from the invite -- these were stored on
        # CompanyInvite specifically because a User row doesn't exist yet
        # at invite-creation time, so they had nowhere else to live until
        # this exact moment.
        job_type=invite.job_type,
        actual_working_hours=invite.actual_working_hours,
        hourly_fee=invite.hourly_fee,
    )
    invite.accepted_at = func.now()
    db.add(user)
    await db.flush()
    return _token_pair(user)


def make_invite(company_id: int, email: str, role: str, team_id: int | None,
                timezone: str | None = None, holiday_country: str | None = None,
                job_type: str = "full_time", actual_working_hours: bool = True,
                hourly_fee: float | None = None) -> CompanyInvite:
    return CompanyInvite(
        company_id=company_id, email=email, role=role, team_id=team_id,
        timezone=timezone, holiday_country=holiday_country,
        job_type=job_type, actual_working_hours=actual_working_hours, hourly_fee=hourly_fee,
        token=secrets.token_urlsafe(32),
    )


def refresh_tokens(user: User) -> TokenPair:
    return _token_pair(user)


def _token_pair(user: User) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user.id, user.company_id, user.role),
        refresh_token=create_refresh_token(user.id, user.company_id, user.role),
    )