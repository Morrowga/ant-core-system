from fastapi import APIRouter, Depends

from app.core.dependencies import DB, ROLE_MANAGER, ROLE_OWNER, CurrentUser, require_role, RequireActivePlan
from app.schemas.reports import (OvertimeOut, OvertimeReportIn, OvertimeRequestDecision,
                                 OvertimeRequestIn, OvertimeRequestOut, OvertimeStart)
from app.services.overtime import OvertimeService

router = APIRouter(prefix="/overtime", tags=["overtime"], dependencies=[RequireActivePlan])
DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))


# ---------- requests (submitted ahead of time, need approval) ----------
@router.post("/requests", response_model=OvertimeRequestOut, status_code=201)
async def create_request(data: OvertimeRequestIn, user: CurrentUser, db: DB):
    return await OvertimeService(db, user).request_overtime(
        data.requested_date, data.planned_start_time, data.planned_end_time, data.reason,
    )


@router.get("/requests/me", response_model=list[OvertimeRequestOut])
async def my_requests(user: CurrentUser, db: DB):
    return await OvertimeService(db, user).my_requests()


@router.get("/requests", response_model=list[OvertimeRequestOut])
async def list_requests(db: DB, employee_id: int | None = None, user=DashUser):
    return await OvertimeService(db, user).list_requests_for_dashboard(employee_id)


@router.patch("/requests/{request_id}", response_model=OvertimeRequestOut)
async def decide_request(request_id: int, data: OvertimeRequestDecision, db: DB, user=DashUser):
    return await OvertimeService(db, user).decide_request(request_id, data.status)


# ---------- sessions (start requires today's approved request) ----------
@router.post("/start", response_model=OvertimeOut, status_code=201)
async def start(data: OvertimeStart, user: CurrentUser, db: DB):
    """409 if no approved OvertimeRequest exists for today -- submit one via
    POST /overtime/requests and wait for approval first."""
    return await OvertimeService(db, user).start(data.project_id)


@router.post("/{overtime_id}/report", response_model=OvertimeOut)
async def attach_report(overtime_id: int, data: OvertimeReportIn, user: CurrentUser, db: DB):
    """Mandatory before /end — platform-locked (business rule 2)."""
    return await OvertimeService(db, user).attach_report(overtime_id, data.summary)


@router.post("/end", response_model=OvertimeOut)
async def end(user: CurrentUser, db: DB):
    """409 if no report attached yet (business rule 2)."""
    return await OvertimeService(db, user).end()


@router.get("/me", response_model=list[OvertimeOut])
async def mine(user: CurrentUser, db: DB, limit: int = 20, offset: int = 0):
    return await OvertimeService(db, user).mine(limit=limit, offset=offset)


@router.get("/{overtime_id}", response_model=OvertimeOut)
async def get_one(overtime_id: int, user: CurrentUser, db: DB):
    """New: single-session detail, matching the same GET /reports/{id}
    pattern -- powers the mobile Overtime detail screen."""
    return await OvertimeService(db, user).get_one(overtime_id)


@router.get("", response_model=list[OvertimeOut])
async def list_overtime(db: DB, employee_id: int | None = None, user=DashUser):
    return await OvertimeService(db, user).list_for_dashboard(employee_id)