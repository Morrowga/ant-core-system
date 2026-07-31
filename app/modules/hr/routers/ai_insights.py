"""AI Insights endpoints -- the two summary modes reachable from Overview's
"Ask your company" entry card. Included in the flat HR module price --
no separate tier gating anymore, RequireActivePlan (HR module enabled) is
the only check needed.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import DB, ROLE_MANAGER, ROLE_OWNER, RequireActivePlan, require_role
from app.modules.hr.services.ai_insights import AIInsightsService

DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))

router = APIRouter(
    prefix="/ai-insights", tags=["ai-insights"],
    dependencies=[RequireActivePlan],
)

# New: separate, UNGATED router for the plain absences list -- this powers
# the Attendance page's new "Absent" tab, which is a deterministic query
# with no LLM call involved, and shouldn't sit behind the same Mid-tier
# plan gate as the AI-generated overview/project summaries above.
attendance_absences_router = APIRouter(prefix="/attendance", tags=["attendance"], dependencies=[RequireActivePlan])


def _parse_dates(period_start: str, period_end: str) -> tuple[date, date]:
    try:
        start = date.fromisoformat(period_start)
        end = date.fromisoformat(period_end)
    except ValueError:
        raise HTTPException(status_code=400, detail="period_start/period_end must be YYYY-MM-DD")
    if start > end:
        raise HTTPException(status_code=400, detail="period_start must be on or before period_end")
    return start, end


@router.get("/overview")
async def overview_summary(
    period_start: str, period_end: str, db: DB, user=DashUser, language: str = "en",
):
    """language: the frontend's CURRENTLY SELECTED UI language (whoever's
    viewing this page right now -- an owner/manager -- not any stored
    per-employee language). Passed straight through to the AI narration
    call; defaults to English if the frontend doesn't send one."""
    start, end = _parse_dates(period_start, period_end)
    return await AIInsightsService(db, user).generate_overview(start, end, language=language)


@router.get("/projects/{project_id}/cooldown")
async def project_cooldown(project_id: int, db: DB, user=DashUser):
    """Lets the frontend check before attempting generation, so it can show
    "come back at HH:MM" without a wasted round trip through the full
    generation flow."""
    return await AIInsightsService(db, user).project_cooldown_status(project_id)


@router.get("/projects/{project_id}")
async def project_summary(
    project_id: int, period_start: str, period_end: str, db: DB, user=DashUser, language: str = "en",
):
    """Same language param/reasoning as overview_summary above."""
    start, end = _parse_dates(period_start, period_end)
    return await AIInsightsService(db, user).generate_project_analysis(
        project_id, start, end, language=language,
    )


@attendance_absences_router.get("/absences")
async def list_absences(period_start: str, period_end: str, db: DB, user=DashUser):
    """Powers the Attendance page's Absent tab. No check-in (or checked in
    more than 2 hours late) on a scheduled workday, excluding holidays,
    weekends, and any day covered by approved leave."""
    start, end = _parse_dates(period_start, period_end)
    return await AIInsightsService(db, user).list_unauthorized_absences(start, end)