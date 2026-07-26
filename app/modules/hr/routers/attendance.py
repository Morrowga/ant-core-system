from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.core.dependencies import DB, ROLE_MANAGER, ROLE_OWNER, CurrentUser, require_role,RequireActivePlan
from app.modules.hr.schemas.attendance import (AttendanceSessionOut, CheckInRequest, DeskLocationIn,
                                    LeaveRequestIn, LeaveRequestOut, LeaveStatusUpdate, LocationPingIn)
from app.modules.hr.services.attendance import AttendanceService

router = APIRouter(prefix="/attendance", tags=["attendance"],dependencies=[RequireActivePlan])
leave_router = APIRouter(prefix="/leave-requests", tags=["attendance"])
DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))


# ---------- employee side ----------
@router.post("/check-in", response_model=AttendanceSessionOut, status_code=201)
async def check_in(data: CheckInRequest, user: CurrentUser, db: DB):
    return await AttendanceService(db, user).check_in(data.lat, data.lng)


@router.post("/check-out", response_model=AttendanceSessionOut)
async def check_out(user: CurrentUser, db: DB):
    return await AttendanceService(db, user).check_out()


@router.post("/ping", status_code=201)
async def location_ping(data: LocationPingIn, user: CurrentUser, db: DB):
    """Rejected with 409 outside an active session (business rule 1)."""
    ping = await AttendanceService(db, user).record_ping(data.lat, data.lng)
    return {"id": ping.id, "recorded_at": ping.recorded_at}


@router.post("/break/start", status_code=201)
async def start_break(user: CurrentUser, db: DB):
    br = await AttendanceService(db, user).start_break()
    return {"id": br.id, "start_at": br.start_at}


@router.post("/break/end")
async def end_break(user: CurrentUser, db: DB):
    br = await AttendanceService(db, user).end_break()
    return {"id": br.id, "start_at": br.start_at, "end_at": br.end_at}


@router.post("/presence-check/{prompt_id}/respond")
async def respond_presence_check(prompt_id: int, payload: dict, user: CurrentUser, db: DB):
    response = payload.get("response")
    if response not in ("yes", "no"):
        raise HTTPException(status_code=400, detail="response must be 'yes' or 'no'")
    prompt = await AttendanceService(db, user).respond_presence_check(prompt_id, response)
    return {"id": prompt.id, "responded_at": prompt.responded_at, "response": prompt.response}


@router.post("/presence-checks/send")
async def send_manual_presence_check(payload: dict, db: DB, user=DashUser):
    """New: replaces automatic presence-check sending entirely. An Owner/
    Manager triggers this on demand for any specific employee they
    suspect needs checking on -- works for both "working outside today"
    employees and normal desk check-ins flagged far from the desk area."""
    employee_id = payload.get("employee_id")
    if not employee_id:
        raise HTTPException(status_code=400, detail="employee_id is required")
    prompt = await AttendanceService(db, user).send_manual_presence_check(int(employee_id))
    return {"id": prompt.id, "sent_at": prompt.sent_at}


@router.get("/presence-checks")
async def list_presence_checks(db: DB, employee_id: int | None = None, user=DashUser):
    """Dashboard-facing: every presence-check prompt (answered, missed, or
    deducted) for the "working outside" flow."""
    rows = await AttendanceService(db, user).presence_checks_for_dashboard(employee_id)
    return [
        {"id": r.id, "user_id": r.user_id, "sent_at": r.sent_at, "responded_at": r.responded_at,
         "response": r.response, "interval_minutes": r.interval_minutes, "deducted": r.deducted,
         "reverted_by": r.reverted_by, "reverted_at": r.reverted_at}
        for r in rows
    ]


@router.post("/presence-checks/{prompt_id}/revert")
async def revert_presence_deduction(prompt_id: int, db: DB, user=DashUser):
    """Manager override: undo an automatic deduction (e.g. it turns out to
    have been a bathroom break or a legitimate call, not actual absence)."""
    prompt = await AttendanceService(db, user).revert_presence_deduction(prompt_id)
    return {"id": prompt.id, "deducted": prompt.deducted, "reverted_at": prompt.reverted_at}


@router.post("/desk-location", status_code=201)
async def set_desk_location(data: DeskLocationIn, user: CurrentUser, db: DB):
    loc = await AttendanceService(db, user).set_desk_location(data.lat, data.lng)
    return {"id": loc.id}


@router.post("/desk-location/request", status_code=201)
async def request_desk_location_change(data: DeskLocationIn, user: CurrentUser, db: DB):
    """New: desk location changes require Owner/Manager approval -- this
    creates a pending request and notifies them, rather than applying the
    change immediately."""
    req = await AttendanceService(db, user).request_desk_location_change(data.lat, data.lng)
    return {"id": req.id, "status": req.status}


@router.get("/desk-location/me")
async def my_desk_location_history(user: CurrentUser, db: DB):
    return await AttendanceService(db, user).my_desk_location_history()


@router.get("/{employee_id}/desk-location")
async def employee_desk_location(employee_id: int, db: DB, user=DashUser):
    """Dashboard-facing: full history + pending/decided requests for one
    employee -- powers the Employee Detail page's Desk Location tab."""
    return await AttendanceService(db, user).desk_location_for_dashboard(employee_id)


@router.patch("/desk-location/requests/{request_id}")
async def decide_desk_location_request(request_id: int, payload: dict, db: DB, user=DashUser):
    status = payload.get("status")
    req = await AttendanceService(db, user).decide_desk_location_request(request_id, status)
    return {"id": req.id, "status": req.status, "decided_at": req.decided_at}


def _parse_roles(raw) -> set[str]:
    """Settings UI may send this as a comma-separated string or as a JSON
    array depending on how it was submitted -- handle both rather than
    assume one, since guessing wrong here means a silent crash."""
    if raw is None:
        return set()
    if isinstance(raw, list):
        return {str(r).strip() for r in raw if str(r).strip()}
    return {r.strip() for r in str(raw).split(",") if r.strip()}


@router.post("/work-outside", status_code=201)
async def work_outside_today(payload: dict, user: CurrentUser, db: DB):
    """Reason is now required -- was previously just an unconditional flag
    with no explanation captured at all.

    New: actually checks the company's "Allow work outside override" and
    "Roles allowed to use the override" settings -- these existed in the
    Settings UI already but were never read anywhere, so the feature was
    always available to everyone regardless of what was configured."""
    from app.modules.hr.models.attendance import WorkOutsideOverride
    from app.core.models.company import CompanySettings

    attendance_settings_row = (await db.execute(
        select(CompanySettings).where(
            CompanySettings.company_id == user.company_id, CompanySettings.section == "attendance",
        )
    )).scalar_one_or_none()
    settings_data = attendance_settings_row.data_json if attendance_settings_row else {}

    if not settings_data.get("allow_work_outside_override", True):
        raise HTTPException(status_code=403, detail="Working outside today has been disabled by your company.")

    allowed_roles = _parse_roles(settings_data.get("work_outside_override_roles"))
    if allowed_roles and user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Your role is not allowed to use this override.")

    reason = (payload.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A reason is required")
    row = WorkOutsideOverride(user_id=user.id, date=date.today(), active=True, reason=reason)
    db.add(row)
    await db.flush()
    return {"id": row.id, "date": str(row.date), "reason": row.reason}


@router.post("/work-outside/cancel")
async def cancel_work_outside(user: CurrentUser, db: DB):
    """Turns "working outside today" back off -- reverts to normal
    desk-location tracking and stops presence-check pings for the rest of
    today."""
    await AttendanceService(db, user).cancel_work_outside()
    return {"ok": True}


@router.get("/me/status")
async def my_status(user: CurrentUser, db: DB):
    return await AttendanceService(db, user).my_status()


@router.get("/me/today-invoice")
async def my_today_invoice(user: CurrentUser, db: DB):
    """Checkout invoice breakdown: scheduled shift length, elapsed time,
    break minutes (excluded, not a penalty), late minutes and no-response
    minutes (the ONLY two deduction sources that exist), and the final
    credited minutes -- gated by the company's late_no_response_deduction_enabled
    setting."""
    return await AttendanceService(db, user).today_invoice()


@router.get("/me/shift-status")
async def my_shift_status(user: CurrentUser, db: DB):
    """New: local shift start/end, late status, and countdowns -- powers
    the mobile home screen's clock/late/countdown display."""
    return await AttendanceService(db, user).shift_status()


@router.get("/me/history", response_model=list[AttendanceSessionOut])
async def my_history(user: CurrentUser, db: DB):
    return await AttendanceService(db, user).my_history()


# ---------- dashboard side ----------
@router.get("/logs")
async def logs(db: DB, employee_id: int | None = None, user=DashUser):
    return await AttendanceService(db, user).logs(employee_id)


@router.get("/working-outside-today")
async def working_outside_today(db: DB, user=DashUser):
    """New: Owner/Manager view of everyone confirmed working outside today,
    with their stated reason. Manager sees own team only (enforced in the
    service)."""
    return await AttendanceService(db, user).working_outside_today()


@router.get("/live-status")
async def live_status(db: DB, user=DashUser):
    from app.modules.hr.models.attendance import AttendanceSession
    from app.core.models.user import User
    svc = AttendanceService(db, user)
    stmt = (select(User.id, User.full_name, AttendanceSession.check_in_at, AttendanceSession.checked_in_outside_desk)
            .join(AttendanceSession, AttendanceSession.user_id == User.id)
            .where(User.company_id == svc.company_id, AttendanceSession.check_out_at.is_(None)))
    if user.role == ROLE_MANAGER:
        stmt = stmt.where(User.team_id == user.team_id)
    rows = (await db.execute(stmt)).all()
    # Frontend's LiveStatusRow type (and component code) reads `name`, not
    # `full_name` -- this key was never matching, so the "Employee #X"
    # fallback fired unconditionally for every single row.
    return [{"user_id": r.id, "name": r.full_name, "checked_in_at": r.check_in_at,
             "checked_in_outside_desk": r.checked_in_outside_desk} for r in rows]


@router.get("/{employee_id}/location-history")
async def location_history(employee_id: int, db: DB, day: date | None = None, user=DashUser):
    """New: each ping now includes `inside_geofence` -- computed the same
    way as check-in's own outside-desk detection (Haversine distance vs.
    the employee's saved desk location, compared against the company's
    configured geofence radius). Previously every ping showed identically
    regardless of how far it actually was from the desk."""
    from app.modules.hr.models.attendance import AttendanceSession, DeskLocation, LocationPing
    from app.core.models.company import CompanySettings
    from app.modules.hr.services.attendance import DEFAULT_DESK_AREA_RADIUS_METERS, _distance_meters

    svc = AttendanceService(db, user)
    target = await svc.assert_user_in_tenant(employee_id)
    if not svc.can_view_employee(target):
        raise HTTPException(status_code=403, detail="Not allowed for this employee")

    stmt = (select(LocationPing)
            .join(AttendanceSession, AttendanceSession.id == LocationPing.attendance_session_id)
            .where(AttendanceSession.user_id == employee_id)
            .order_by(LocationPing.recorded_at.desc()).limit(1000))
    pings = (await db.execute(stmt)).scalars().all()

    desk = (await db.execute(
        select(DeskLocation).where(DeskLocation.user_id == employee_id)
        .order_by(DeskLocation.set_at.desc()).limit(1)
    )).scalars().first()

    attendance_settings_row = (await db.execute(
        select(CompanySettings).where(
            CompanySettings.company_id == user.company_id, CompanySettings.section == "attendance",
        )
    )).scalar_one_or_none()
    radius = (
        attendance_settings_row.data_json.get("default_geofence_radius_m", DEFAULT_DESK_AREA_RADIUS_METERS)
        if attendance_settings_row else DEFAULT_DESK_AREA_RADIUS_METERS
    )

    out = []
    for p in pings:
        if day is not None and p.recorded_at.date() != day:
            continue
        inside_geofence = None  # unknown if no desk location has ever been set
        if desk is not None:
            distance = _distance_meters(p.lat, p.lng, desk.lat, desk.lng)
            inside_geofence = distance <= radius
        out.append({"latitude": p.lat, "longitude": p.lng, "pinged_at": p.recorded_at,
                    "inside_geofence": inside_geofence})
    return out


# ---------- leave requests ----------
@leave_router.post("", response_model=LeaveRequestOut, status_code=201)
async def create_leave(data: LeaveRequestIn, user: CurrentUser, db: DB):
    return await AttendanceService(db, user).create_leave(
        data.type, data.start_date, data.end_date,
        start_time=getattr(data, "start_time", None), end_time=getattr(data, "end_time", None),
    )


@leave_router.get("/me", response_model=list[LeaveRequestOut])
async def my_leaves(user: CurrentUser, db: DB):
    from app.modules.hr.models.attendance import LeaveRequest
    res = await db.execute(select(LeaveRequest).where(LeaveRequest.user_id == user.id)
                           .order_by(LeaveRequest.requested_at.desc()))
    return list(res.scalars())


@leave_router.get("")
async def list_leaves(db: DB, user=DashUser):
    """New: joins to User to actually include the employee's name --
    previously returned raw LeaveRequest rows with no name resolution at
    all, so the dashboard's `leave.employee_name ?? Employee #X` fallback
    fired unconditionally for every single request."""
    from app.modules.hr.models.attendance import LeaveRequest
    from app.core.models.user import User

    svc = AttendanceService(db, user)
    stmt = (
        select(LeaveRequest, User.full_name)
        .join(User, User.id == LeaveRequest.user_id)
        .where(User.company_id == svc.company_id)
        .order_by(LeaveRequest.requested_at.desc())
    )
    if user.role == ROLE_MANAGER:
        stmt = stmt.where(User.team_id == user.team_id)

    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": lr.id, "user_id": lr.user_id, "type": lr.type,
            "start_date": lr.start_date, "end_date": lr.end_date,
            "start_time": lr.start_time, "end_time": lr.end_time,
            "status": lr.status, "requested_at": lr.requested_at,
            "employee_name": full_name,
        }
        for lr, full_name in rows
    ]


@leave_router.patch("/{leave_id}", response_model=LeaveRequestOut)
async def decide_leave(leave_id: int, data: LeaveStatusUpdate, db: DB, user=DashUser):
    from app.modules.hr.models.attendance import LeaveRequest
    svc = AttendanceService(db, user)
    lr = await db.get(LeaveRequest, leave_id)
    if lr is None:
        raise HTTPException(status_code=404, detail="Leave request not found")
    target = await svc.assert_user_in_tenant(lr.user_id)
    if not svc.can_view_employee(target):
        raise HTTPException(status_code=403, detail="Not allowed for this employee")
    if data.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid status")
    lr.status = data.status
    await db.flush()
    return lr