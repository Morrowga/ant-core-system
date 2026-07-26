from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.core.dependencies import (DB, ROLE_MANAGER, ROLE_OWNER, CurrentUser,
                                   require_role, RequireActivePlan)
from app.core.services.base import TenantService

DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))
Owner = Depends(require_role([ROLE_OWNER]))

onboarding_router = APIRouter(tags=["onboarding"], dependencies=[RequireActivePlan])


@onboarding_router.get("/onboarding/me")
async def my_onboarding(user: CurrentUser, db: DB):
    from app.modules.hr.models.misc import EmployeeOnboardingProgress, OnboardingChecklistItem
    svc = TenantService(db, user)
    items = list((await db.execute(svc.tenant_select(OnboardingChecklistItem)
                                   .order_by(OnboardingChecklistItem.order))).scalars())
    done_ids = {p.checklist_item_id for p in (await db.execute(
        select(EmployeeOnboardingProgress).where(EmployeeOnboardingProgress.user_id == user.id))).scalars()}
    return [{"id": i.id, "title": i.title, "type": i.type, "required": i.required,
             "completed": i.id in done_ids} for i in items]


@onboarding_router.post("/onboarding/me/{item_id}/complete", status_code=201)
async def complete_item(item_id: int, user: CurrentUser, db: DB):
    from datetime import datetime, timezone
    from app.modules.hr.models.misc import EmployeeOnboardingProgress, OnboardingChecklistItem
    item = await db.get(OnboardingChecklistItem, item_id)
    if item is None or item.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    db.add(EmployeeOnboardingProgress(user_id=user.id, checklist_item_id=item_id))
    await db.flush()
    # Mark onboarding complete when all required items are done.
    svc = TenantService(db, user)
    required_ids = {i.id for i in (await db.execute(
        svc.tenant_select(OnboardingChecklistItem).where(OnboardingChecklistItem.required.is_(True)))).scalars()}
    done_ids = {p.checklist_item_id for p in (await db.execute(
        select(EmployeeOnboardingProgress).where(EmployeeOnboardingProgress.user_id == user.id))).scalars()}
    if required_ids and required_ids.issubset(done_ids) and user.onboarding_completed_at is None:
        user.onboarding_completed_at = datetime.now(timezone.utc)
    await db.flush()
    return {"ok": True}


# ---------------- admin/dashboard side ----------------

@onboarding_router.get("/company/settings/onboarding-checklist")
async def list_checklist(db: DB, user=DashUser):
    from app.modules.hr.models.misc import OnboardingChecklistItem
    svc = TenantService(db, user)
    items = (await db.execute(svc.tenant_select(OnboardingChecklistItem)
                              .order_by(OnboardingChecklistItem.order))).scalars()
    return [{"id": i.id, "title": i.title, "type": i.type, "required": i.required,
             "linked_knowledge_post_id": i.linked_knowledge_post_id, "order": i.order}
            for i in items]


@onboarding_router.post("/company/settings/onboarding-checklist", status_code=201)
async def create_checklist_item(payload: dict, db: DB, user=Owner):
    from app.modules.hr.models.misc import OnboardingChecklistItem
    item = OnboardingChecklistItem(
        company_id=user.company_id, title=payload.get("title", ""),
        type=payload.get("type", "task"),
        linked_knowledge_post_id=payload.get("linked_knowledge_post_id"),
        required=bool(payload.get("required", True)),
        order=int(payload.get("order", 0)))
    if item.type not in ("task", "read", "watch"):
        raise HTTPException(status_code=400, detail="type must be task|read|watch")
    db.add(item)
    await db.flush()
    return {"id": item.id}


@onboarding_router.patch("/company/settings/onboarding-checklist/{item_id}")
async def update_checklist_item(item_id: int, payload: dict, db: DB, user=Owner):
    item = await _item_in_tenant(db, user, item_id)
    for field in ("title", "type", "linked_knowledge_post_id", "required", "order"):
        if field in payload:
            setattr(item, field, payload[field])
    await db.flush()
    return {"ok": True}


@onboarding_router.delete("/company/settings/onboarding-checklist/{item_id}", status_code=204)
async def delete_checklist_item(item_id: int, db: DB, user=Owner):
    item = await _item_in_tenant(db, user, item_id)
    await db.delete(item)
    return None


@onboarding_router.get("/onboarding")
async def onboarding_overview(db: DB, status: str = "in_progress", user=DashUser):
    """Employees still inside their first 30 days (or all, with ?status=all)."""
    from datetime import datetime, timedelta, timezone
    from app.core.models.user import User as UserModel
    svc = TenantService(db, user)
    stmt = svc.tenant_select(UserModel).where(UserModel.active.is_(True))
    if status == "in_progress":
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        stmt = stmt.where(UserModel.joined_at >= cutoff)
    if user.role == "manager":  # managers see their own team only
        stmt = stmt.where(UserModel.team_id == user.team_id)
    rows = (await db.execute(stmt.order_by(UserModel.joined_at.desc()))).scalars()
    out = []
    for u in rows:
        pct, _, _ = await _completion(db, user, u.id)
        out.append({"employee_id": u.id, "name": u.full_name, "joined_at": u.joined_at,
                    "completion_pct": pct,
                    "onboarding_completed_at": u.onboarding_completed_at})
    return out


@onboarding_router.get("/onboarding/{employee_id}")
async def employee_onboarding(employee_id: int, db: DB, user=DashUser):
    from datetime import date, datetime, timedelta, timezone
    from app.modules.hr.services.performance import PerformanceService

    svc = PerformanceService(db, user)
    target = await svc._target(employee_id)  # tenant + team-scope check

    pct, items, done_ids = await _completion(db, user, employee_id)
    days_since_joined = (datetime.now(timezone.utc) - target.joined_at).days if target.joined_at else None

    # Pace trend: one label per day over the last 14 days (from stored analyses).
    today = date.today()
    paces = await svc.daily_pace_labels(employee_id, today - timedelta(days=14), today)
    pace_trend = [{"date": str(d), "pace": label} for d, label in sorted(paces.items())]

    # reached_team_baseline_on: first day this employee's reported hours met or
    # exceeded the team's average DAILY hours (computed over the same window).
    # Documented choice: baseline = team avg daily hours over the employee's tenure.
    baseline_on = None
    joined = target.joined_at.date() if target.joined_at else today
    my_hours = await svc.daily_hours(employee_id, joined, today)
    if my_hours and target.team_id:
        from sqlalchemy import func, select as sa_select
        from app.modules.hr.models.reports import Report
        from app.core.models.user import User as UserModel
        team_avg_daily = await db.scalar(
            sa_select(func.coalesce(func.sum(Report.hours), 0)
                      / func.greatest(func.count(func.distinct(Report.report_date)), 1)
                      / func.greatest(func.count(func.distinct(Report.user_id)), 1))
            .join(UserModel, UserModel.id == Report.user_id)
            .where(UserModel.team_id == target.team_id, UserModel.id != employee_id,
                   Report.report_date >= joined))
        team_avg_daily = float(team_avg_daily or 0)
        if team_avg_daily > 0:
            for d in sorted(my_hours):
                if my_hours[d] >= team_avg_daily:
                    baseline_on = str(d)
                    break

    return {"employee_id": employee_id, "name": target.full_name,
            "checklist": items, "completion_pct": pct,
            "days_since_joined": days_since_joined,
            "workload_pace_trend": pace_trend,
            "reached_team_baseline_on": baseline_on}


async def _item_in_tenant(db, user, item_id: int):
    from app.modules.hr.models.misc import OnboardingChecklistItem
    item = await db.get(OnboardingChecklistItem, item_id)
    if item is None or item.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    return item


async def _completion(db, user, employee_id: int):
    from app.modules.hr.models.misc import EmployeeOnboardingProgress, OnboardingChecklistItem
    svc = TenantService(db, user)
    items = list((await db.execute(svc.tenant_select(OnboardingChecklistItem)
                                   .order_by(OnboardingChecklistItem.order))).scalars())
    done_ids = {p.checklist_item_id for p in (await db.execute(
        select(EmployeeOnboardingProgress).where(
            EmployeeOnboardingProgress.user_id == employee_id))).scalars()}
    payload = [{"id": i.id, "title": i.title, "type": i.type, "required": i.required,
                "completed": i.id in done_ids} for i in items]
    pct = round(len([i for i in items if i.id in done_ids]) / len(items) * 100, 1) if items else 100.0
    return pct, payload, done_ids
