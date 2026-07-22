from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.core.dependencies import DB, ROLE_MANAGER, ROLE_OWNER, CurrentUser, require_role, RequireActivePlan
from app.models.misc import HealthCheckinPrompt
from app.schemas.health import (HealthCheckinPromptOut, HealthLogOut, MoodIn, SleepIn,
                                TeamWellbeingPoint, WaterIn)
from app.services.health import HealthService

router = APIRouter(prefix="/health", tags=["health"], dependencies=[RequireActivePlan])


async def _mark_prompt_responded(db: DB, user_id: int, prompt_id: int | None) -> None:
    """Shared by water/mood/sleep -- if this submission is answering a
    specific reminder, stamp it responded so it drops off the "unanswered"
    list (Health tab banner + the report-submission gate)."""
    if prompt_id is None:
        return
    prompt = await db.get(HealthCheckinPrompt, prompt_id)
    if prompt is not None and prompt.user_id == user_id and prompt.responded_at is None:
        prompt.responded_at = datetime.now(timezone.utc)
        await db.flush()


# ---------- self-only ----------
@router.post("/water", response_model=HealthLogOut, status_code=201)
async def log_water(data: WaterIn, user: CurrentUser, db: DB):
    result = await HealthService(db, user).log("water", data.ml)
    await _mark_prompt_responded(db, user.id, data.prompt_id)
    return result


@router.get("/water/me", response_model=list[HealthLogOut])
async def my_water(user: CurrentUser, db: DB):
    return await HealthService(db, user).my_logs("water", since_days=1)


@router.post("/mood", response_model=HealthLogOut, status_code=201)
async def log_mood(data: MoodIn, user: CurrentUser, db: DB):
    result = await HealthService(db, user).log("mood", data.mood)
    await _mark_prompt_responded(db, user.id, data.prompt_id)
    return result


@router.get("/mood/me", response_model=list[HealthLogOut])
async def my_mood(user: CurrentUser, db: DB):
    return await HealthService(db, user).my_logs("mood")


@router.post("/break-ack", response_model=HealthLogOut, status_code=201)
async def break_ack(user: CurrentUser, db: DB):
    return await HealthService(db, user).log("break_ack", 1)


@router.post("/sleep", response_model=HealthLogOut, status_code=201)
async def log_sleep(data: SleepIn, user: CurrentUser, db: DB):
    result = await HealthService(db, user).log("sleep", data.hours)
    await _mark_prompt_responded(db, user.id, data.prompt_id)
    return result


@router.get("/me/dashboard")
async def my_health_dashboard(user: CurrentUser, db: DB):
    return await HealthService(db, user).my_dashboard()


# ---------- check-in prompts (this reminder system) ----------
@router.get("/prompts/pending", response_model=list[HealthCheckinPromptOut])
async def pending_prompts(user: CurrentUser, db: DB):
    """Unanswered reminders -- powers the Health tab's "you have an
    unanswered check-in" banner and the report-submission gate."""
    stmt = (
        select(HealthCheckinPrompt)
        .where(HealthCheckinPrompt.user_id == user.id, HealthCheckinPrompt.responded_at.is_(None))
        .order_by(HealthCheckinPrompt.sent_at.desc())
    )
    return list((await db.execute(stmt)).scalars())


@router.get("/prompts/today", response_model=list[HealthCheckinPromptOut])
async def todays_prompts(user: CurrentUser, db: DB):
    """Full daily list (answered + unanswered), for the Health tab's summary."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(HealthCheckinPrompt)
        .where(HealthCheckinPrompt.user_id == user.id, HealthCheckinPrompt.sent_at >= today_start)
        .order_by(HealthCheckinPrompt.sent_at.asc())
    )
    return list((await db.execute(stmt)).scalars())


# ---------- team view: AGGREGATED ONLY (business rule 5, platform-locked) ----------
@router.get("/team-wellbeing-trend", response_model=list[TeamWellbeingPoint])
async def team_wellbeing(
    db: DB,
    team_id: int | None = Query(None, description="Omit for company-wide (or manager's own team)"),
    user=Depends(require_role([ROLE_OWNER, ROLE_MANAGER])),
):
    """No endpoint exists that returns per-user health rows to owner/manager —
    this is the only management-facing health route and it aggregates with a
    minimum group size. team_id omitted = company-wide for owner_admin,
    or the manager's own team automatically for manager."""
    return await HealthService(db, user).team_wellbeing_trend(team_id)