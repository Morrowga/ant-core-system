import re
import secrets
import string

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.models.company import Company, CompanyInvite, Subscription
from app.models.users import User
from app.schemas.auth import AcceptInviteRequest, CompanyRegisterRequest, LoginRequest, TokenPair

# Crockford-ish alphabet -- excludes 0/O and 1/I/L, the characters most
# often confused when a person is reading a code off a screen and typing
# it into a phone. Also excludes vowels-that-spell-words as a side effect
# of using this restricted set (not a hard requirement, just a bonus).
SHORT_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
SHORT_CODE_LENGTH = 6


def _slugify_company_name(name: str) -> str:
    """"Northwind Trading Co." -> "NORTHWIND". Takes just the first
    alphanumeric word, uppercased -- keeps the prefix short and readable
    rather than slugifying the entire company name (which could be long
    or contain characters awkward to type on a phone keyboard)."""
    match = re.search(r"[A-Za-z0-9]+", name)
    word = match.group(0) if match else "COMPANY"
    return word.upper()[:20]  # hard cap so a very long single word doesn't blow out the column


def _generate_short_code(company_name: str) -> str:
    prefix = _slugify_company_name(company_name)
    suffix = "".join(secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH))
    return f"{prefix}-{suffix}"


async def _unique_short_code(db: AsyncSession, company_name: str) -> str:
    """Regenerates on the rare collision -- short codes are drawn from a
    large-enough space (32^6 for the suffix alone) that collisions should
    be extremely rare, but this guards against it rather than assuming."""
    for _ in range(10):
        candidate = _generate_short_code(company_name)
        existing = await db.execute(select(CompanyInvite).where(CompanyInvite.short_code == candidate))
        if existing.scalar_one_or_none() is None:
            return candidate
    raise HTTPException(status_code=500, detail="Could not generate a unique invite code, please try again")


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
    # Accept either the long token (deep link) or the short human-typed
    # code -- whatever was pasted/typed into the single input field.
    # Trying both in one query rather than two round trips.
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

    user = User(
        company_id=invite.company_id,
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
    """Now async and takes `db` -- needed to read the company's name for
    the short code prefix, and to check for short-code collisions before
    the row is actually created."""
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
        access_token=create_access_token(user.id, user.company_id, user.role),
        refresh_token=create_refresh_token(user.id, user.company_id, user.role),
    )