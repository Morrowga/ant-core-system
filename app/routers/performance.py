"""Performance endpoints — read-only, Owner/Admin/Manager (manager: own team only,
enforced via can_view_employee / team checks inside PerformanceService)."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.dependencies import DB, ROLE_MANAGER, ROLE_OWNER, require_role
from app.services.performance import PerformanceService

router = APIRouter(prefix="/performance", tags=["performance"])
DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))

DEFAULT_PERIOD_DAYS = 30


def _parse_range(date_range: str | None) -> tuple[date, date]:
    """Accepts 'YYYY-MM-DD:YYYY-MM-DD'; defaults to the last 30 days."""
    if not date_range:
        end = date.today()
        return end - timedelta(days=DEFAULT_PERIOD_DAYS), end
    try:
        start_s, end_s = date_range.split(":")
        start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)
    except ValueError:
        raise HTTPException(status_code=400, detail="date_range must be YYYY-MM-DD:YYYY-MM-DD")
    if start > end:
        raise HTTPException(status_code=400, detail="date_range start is after end")
    return start, end


@router.get("/attendance-reliability")
async def attendance_reliability(db: DB, employee_id: int = Query(...),
                                 date_range: str | None = None, user=DashUser):
    start, end = _parse_range(date_range)
    svc = PerformanceService(db, user)
    target = await svc._target(employee_id)
    result = await svc.attendance_reliability(target, start, end)
    return {"employee_id": employee_id, "period": {"start": str(start), "end": str(end)}, **result}


@router.get("/team/{team_id}/comparison")
async def team_comparison(team_id: int, db: DB, date_range: str | None = None, user=DashUser):
    start, end = _parse_range(date_range)
    return await PerformanceService(db, user).team_comparison(team_id, start, end)


@router.get("/{employee_id}/daily-list")
async def daily_list(employee_id: int, db: DB, date_range: str | None = None, user=DashUser):
    start, end = _parse_range(date_range)
    return await PerformanceService(db, user).daily_list(employee_id, start, end)


@router.get("/{employee_id}/impact-score")
async def impact_score(employee_id: int, db: DB, date_range: str | None = None, user=DashUser):
    start, end = _parse_range(date_range)
    return await PerformanceService(db, user).impact_score(employee_id, start, end)
