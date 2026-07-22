from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.core.dependencies import DB, ROLE_OWNER, CurrentUser, require_role
from app.models.company import Company, CompanyInvite
from app.schemas.users import ConsentIn, InviteCreate, UserOut, UserUpdate
from app.services import auth as auth_service

router = APIRouter(tags=["company"])


@router.get("/company/me")
async def get_company(user: CurrentUser, db: DB):
    company = await db.get(Company, user.company_id)
    return {"id": company.id, "name": company.name, "logo_url": company.logo_url,
            "industry": company.industry, "timezone": company.timezone, "currency": company.currency,
            "working_hours_start": company.working_hours_start,
            "working_hours_end": company.working_hours_end, "workdays": company.workdays}


@router.patch("/company/me")
async def update_company(payload: dict, db: DB, user=Depends(require_role([ROLE_OWNER]))):
    company = await db.get(Company, user.company_id)
    for field in ("name", "logo_url", "industry", "timezone", "currency",
                  "working_hours_start", "working_hours_end", "workdays"):
        if field in payload:
            setattr(company, field, payload[field])
    await db.flush()
    return {"ok": True}


@router.post("/company/invite", status_code=201)
async def create_invite(data: InviteCreate, db: DB, user=Depends(require_role([ROLE_OWNER]))):
    if data.role not in ("owner_admin", "manager", "employee"):
        raise HTTPException(status_code=400, detail="Invalid role")

    from sqlalchemy import func
    from app.models.users import User
    from app.integrations.stripe_client import SEAT_LIMITS
    from app.models.company import Subscription

    sub = (await db.execute(select(Subscription).where(
        Subscription.company_id == user.company_id))).scalar_one_or_none()
    seat_limit = SEAT_LIMITS.get(sub.plan_tier if sub else "startup")

    if seat_limit is not None:
        active_count = await db.scalar(select(func.count(User.id)).where(
            User.company_id == user.company_id, User.active.is_(True)))
        pending_invite_count = await db.scalar(select(func.count(CompanyInvite.id)).where(
            CompanyInvite.company_id == user.company_id, CompanyInvite.accepted_at.is_(None)))
        if (active_count or 0) + (pending_invite_count or 0) >= seat_limit:
            raise HTTPException(
                status_code=402,
                detail=f"Seat limit reached ({seat_limit} seats on your current plan). Upgrade to invite more people.",
            )

    invite = auth_service.make_invite(
        user.company_id, data.email, data.role, data.team_id, data.timezone, data.holiday_country,
        job_type=data.job_type, actual_working_hours=data.actual_working_hours, hourly_fee=data.hourly_fee,
    )
    db.add(invite)
    await db.flush()
    return {"id": invite.id, "email": invite.email, "token": invite.token}


@router.get("/company/invites")
async def list_invites(db: DB, user=Depends(require_role([ROLE_OWNER]))):
    """Was returning every invite ever sent, accepted or not -- the
    dashboard's "Pending invites" list had no way to tell the difference,
    so accepted invites kept showing up as if still pending."""
    res = await db.execute(select(CompanyInvite).where(
        CompanyInvite.company_id == user.company_id,
        CompanyInvite.accepted_at.is_(None),
    ))
    return [{"id": i.id, "email": i.email, "role": i.role, "accepted_at": i.accepted_at} for i in res.scalars()]


@router.delete("/company/invite/{invite_id}", status_code=204)
async def delete_invite(invite_id: int, db: DB, user=Depends(require_role([ROLE_OWNER]))):
    invite = await db.get(CompanyInvite, invite_id)
    if invite is None or invite.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="Invite not found")
    await db.delete(invite)
    return None


# ---- employee-side profile & consent ----
@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user


@router.patch("/me", response_model=UserOut)
async def update_me(data: UserUpdate, user: CurrentUser, db: DB):
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.avatar_url is not None:
        user.avatar_url = data.avatar_url
    await db.flush()
    return user


@router.post("/consent", status_code=201)
async def record_consent(data: ConsentIn, user: CurrentUser, db: DB):
    from app.models.users import Consent
    if data.type not in ("location", "health", "notifications"):
        raise HTTPException(status_code=400, detail="Invalid consent type")
    row = Consent(user_id=user.id, type=data.type, accepted=data.accepted)
    db.add(row)
    await db.flush()
    return {"id": row.id}


@router.get("/consent/me")
async def my_consents(user: CurrentUser, db: DB):
    from app.models.users import Consent
    res = await db.execute(select(Consent).where(Consent.user_id == user.id).order_by(Consent.recorded_at.desc()))
    return [{"type": c.type, "accepted": c.accepted, "recorded_at": c.recorded_at} for c in res.scalars()]


@router.get("/me/team")
async def my_team(user: CurrentUser, db: DB):
    from app.models.users import Team, User
    if user.team_id is None:
        return {"team": None, "members": []}
    team = await db.get(Team, user.team_id)
    res = await db.execute(select(User).where(User.team_id == user.team_id,
                                              User.company_id == user.company_id, User.active.is_(True)))
    return {"team": {"id": team.id, "name": team.name},
            "members": [{"id": m.id, "full_name": m.full_name} for m in res.scalars()]}


@router.get("/company/info")
async def company_info(user: CurrentUser, db: DB):
    company = await db.get(Company, user.company_id)
    return {"name": company.name, "logo_url": company.logo_url, "timezone": company.timezone}