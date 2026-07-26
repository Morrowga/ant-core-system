from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.core.dependencies import DB, ROLE_OWNER, CurrentUser, require_role
from app.core.models.company import Company, CompanyInvite
from app.core.models.company_module import CompanyModule
from app.core.schemas.users import ConsentIn, InviteCreate, UserOut, UserUpdate
from app.core.services import auth as auth_service

router = APIRouter(tags=["company"])


@router.get("/company/me")
async def get_company(user: CurrentUser, db: DB):
    if user.company_id is None:
        raise HTTPException(status_code=409, detail="Create a company first.")
    company = await db.get(Company, user.company_id)
    return {"id": company.id, "name": company.name, "logo_url": company.logo_url,
            "industry": company.industry, "timezone": company.timezone, "currency": company.currency,
            "working_hours_start": company.working_hours_start,
            "working_hours_end": company.working_hours_end, "workdays": company.workdays}


@router.post("/me/onboarding-complete", response_model=UserOut)
async def complete_onboarding(user: CurrentUser, db: DB):
    """Marks this user's onboarding as done, server-side. Replaces the old
    mobile-only SecureStore flag, which was scoped to the DEVICE rather
    than the user -- meaning a second account tested on the same
    simulator/phone incorrectly inherited "already onboarded" from
    whichever account onboarded there first."""
    from datetime import datetime, timezone
    user.onboarding_completed_at = datetime.now(timezone.utc)
    await db.flush()
    return user

@router.post("/company/invite", status_code=201)
async def create_invite(data: InviteCreate, db: DB, user=Depends(require_role([ROLE_OWNER]))):
    if user.company_id is None:
        raise HTTPException(status_code=409, detail="Create a company first.")
    if data.role not in ("owner_admin", "manager", "employee"):
        raise HTTPException(status_code=400, detail="Invalid role")

    # New: flat, per-module pricing has no seat limit -- limits only ever
    # existed to differentiate Startup/Mid/Enterprise tiers, which no
    # longer exist. A company enabling the HR module can invite as many
    # people as it wants; seats_used is still tracked (see billing.py) as
    # informational usage data, but nothing here blocks on it.

    invite = await auth_service.make_invite(
        db, user.company_id, data.email, data.role, data.team_id, data.timezone, data.holiday_country,
        job_type=data.job_type, actual_working_hours=data.actual_working_hours, hourly_fee=data.hourly_fee,
        language=data.language,
    )
    db.add(invite)
    await db.flush()
    # New: short_code returned alongside the existing long token -- the
    # frontend can now show/copy either, e.g. the short code for reading
    # aloud or manual entry, the token for a deep-link URL.
    return {"id": invite.id, "email": invite.email, "token": invite.token, "short_code": invite.short_code}


@router.get("/company/invites")
async def list_invites(db: DB, user=Depends(require_role([ROLE_OWNER]))):
    """Was returning every invite ever sent, accepted or not -- the
    dashboard's "Pending invites" list had no way to tell the difference,
    so accepted invites kept showing up as if still pending."""
    res = await db.execute(select(CompanyInvite).where(
        CompanyInvite.company_id == user.company_id,
        CompanyInvite.accepted_at.is_(None),
    ))
    return [{"id": i.id, "email": i.email, "role": i.role, "short_code": i.short_code, "accepted_at": i.accepted_at}
            for i in res.scalars()]


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
    """Note: this was previously defined TWICE in this file -- the second
    definition (without the language handling) silently won at import
    time, meaning language changes from Settings/Language screens have
    likely never actually persisted. Merged into one correct definition."""
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.avatar_url is not None:
        user.avatar_url = data.avatar_url
    if data.language is not None:
        if data.language not in ("en", "ja", "ko", "zh", "hi"):
            raise HTTPException(status_code=400, detail="Unsupported language")
        user.language = data.language
    await db.flush()
    return user


@router.post("/consent", status_code=201)
async def record_consent(data: ConsentIn, user: CurrentUser, db: DB):
    from app.core.models.user import Consent
    if data.type not in ("location", "health", "notifications"):
        raise HTTPException(status_code=400, detail="Invalid consent type")
    row = Consent(user_id=user.id, type=data.type, accepted=data.accepted)
    db.add(row)
    await db.flush()
    return {"id": row.id}


@router.get("/consent/me")
async def my_consents(user: CurrentUser, db: DB):
    from app.core.models.user import Consent
    res = await db.execute(select(Consent).where(Consent.user_id == user.id).order_by(Consent.recorded_at.desc()))
    return [{"type": c.type, "accepted": c.accepted, "recorded_at": c.recorded_at} for c in res.scalars()]


@router.get("/me/team")
async def my_team(user: CurrentUser, db: DB):
    from app.core.models.user import Team, User
    if user.team_id is None:
        return {"team": None, "members": []}
    team = await db.get(Team, user.team_id)
    res = await db.execute(select(User).where(User.team_id == user.team_id,
                                              User.company_id == user.company_id, User.active.is_(True)))
    return {"team": {"id": team.id, "name": team.name},
            "members": [{"id": m.id, "full_name": m.full_name} for m in res.scalars()]}


@router.get("/company/info")
async def company_info(user: CurrentUser, db: DB):
    if user.company_id is None:
        raise HTTPException(status_code=409, detail="Create a company first.")
    company = await db.get(Company, user.company_id)
    return {"name": company.name, "logo_url": company.logo_url, "timezone": company.timezone}


@router.get("/me/modules")
async def my_modules(user: CurrentUser, db: DB):
    """Every module THIS person's company currently has active/trialing --
    for the portal/mobile "which module(s) can I actually enter" check on
    boot. Deliberately open to any authenticated user (employee, manager,
    owner alike), unlike GET /billing/companies/me/modules which is
    Owner-only and shows every status (including incomplete/cancelled)
    for billing management -- an employee has no use for that and can't
    act on it anyway.
    """
    if user.company_id is None:
        return []
    res = await db.execute(
        select(CompanyModule).where(
            CompanyModule.company_id == user.company_id,
            CompanyModule.status.in_(["active", "trialing"]),
        )
    )
    return [{"module_key": m.module_key, "status": m.status} for m in res.scalars()]