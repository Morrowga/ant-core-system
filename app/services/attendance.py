"""Attendance + location. Enforces rule 1: pings only inside an active session."""
from datetime import datetime, timezone
from math import atan2, cos, radians, sin, sqrt

from fastapi import HTTPException
from sqlalchemy import select

from app.models.attendance import AttendanceSession, DeskLocation, LeaveRequest, LocationPing
from app.services.base import TenantService

DEFAULT_DESK_AREA_RADIUS_METERS = 300  # fallback only, if the company hasn't configured one


def _distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine great-circle distance -- accurate enough for a 300m radius
    check, no need for anything more precise than this."""
    r = 6_371_000  # Earth radius, meters
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lng2 - lng1)
    a = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


class AttendanceService(TenantService):
    async def _open_session(self, user_id: int) -> AttendanceSession | None:
        res = await self.db.execute(
            select(AttendanceSession)
            .where(AttendanceSession.user_id == user_id, AttendanceSession.check_out_at.is_(None))
            .order_by(AttendanceSession.check_in_at.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def _desk_location(self, user_id: int) -> DeskLocation | None:
        res = await self.db.execute(
            select(DeskLocation).where(DeskLocation.user_id == user_id).order_by(DeskLocation.set_at.desc()).limit(1)
        )
        return res.scalars().first()

    EARLY_CHECK_IN_WINDOW_MINUTES = 15

    async def check_in(self, lat: float | None, lng: float | None) -> AttendanceSession:
        if await self._open_session(self.current_user.id):
            raise HTTPException(status_code=409, detail="Already checked in")

        # New: job_type branches the entire shift-time restriction block.
        # full_time keeps the EXACT existing behavior below, completely
        # unchanged. part_time skips shift-time restrictions entirely (no
        # early-check-in block, no shift-ended block -- their hours are
        # flexible by design), but is limited to exactly ONE check-in/
        # check-out cycle per day, checked using the same mode-aware
        # "today" anchor used everywhere else in this file for consistency.
        is_part_time = getattr(self.current_user, "job_type", "full_time") == "part_time"

        if is_part_time:
            from zoneinfo import ZoneInfo
            from app.models.company import Company

            company = await self.db.get(Company, self.current_user.company_id)
            mode = getattr(company, "working_hours_mode", "company_timezone")
            employee_tz_name = getattr(self.current_user, "timezone", None)
            anchor_name = company.timezone if mode == "company_timezone" else (employee_tz_name or company.timezone)
            try:
                tz = ZoneInfo(anchor_name or "UTC")
            except Exception:
                tz = ZoneInfo("UTC")
            today_local = datetime.now(tz).date()

            recent_sessions = (await self.db.execute(
                select(AttendanceSession).where(AttendanceSession.user_id == self.current_user.id)
                .order_by(AttendanceSession.check_in_at.desc()).limit(5)
            )).scalars().all()
            already_used_today = any(
                (s.check_in_at if s.check_in_at.tzinfo else s.check_in_at.replace(tzinfo=timezone.utc))
                .astimezone(tz).date() == today_local
                for s in recent_sessions
            )
            if already_used_today:
                raise HTTPException(
                    status_code=409,
                    detail="You've already checked in today. Part-time employees get one check-in per day.",
                )
        else:
            # New: block check-in more than 15 minutes before the scheduled
            # shift start -- previously check-in was allowed at any time, even
            # hours before the shift actually begins.
            try:
                from app.models.company import Company
                from app.core.worktime import compute_shift_bounds_utc

                company = await self.db.get(Company, self.current_user.company_id)
                employee_tz_name = getattr(self.current_user, "timezone", None) or company.timezone
                shift_start_utc, shift_end_utc = compute_shift_bounds_utc(
                    company.working_hours_start, company.working_hours_end,
                    company.timezone, employee_tz_name, company.working_hours_mode,
                )
                now = datetime.now(timezone.utc)
                minutes_until_start = (shift_start_utc - now).total_seconds() / 60
                if minutes_until_start > self.EARLY_CHECK_IN_WINDOW_MINUTES:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Check-in opens {self.EARLY_CHECK_IN_WINDOW_MINUTES} minutes before your shift starts "
                                f"— try again closer to your shift time.",
                    )
                # New: also block once the shift has entirely finished --
                # being a FEW minutes late is fine (handled separately via
                # late_minutes), but checking in hours after the whole shift
                # window already closed doesn't correspond to any real shift
                # left to work. Uses the shift's own END time as the cutoff,
                # not some arbitrary grace period.
                if now > shift_end_utc:
                    raise HTTPException(
                        status_code=409,
                        detail="Today's shift has already ended. Check-in is no longer available for today.",
                    )
            except HTTPException:
                raise
            except Exception:
                pass  # never let shift-time math block a check-in if something's misconfigured

        # New: block regular check-in on a holiday (this employee's assigned
        # country, or a company-wide holiday) -- UNLESS they have an
        # approved overtime request for today, in which case they should
        # use the Overtime page's start flow instead of regular check-in.
        from datetime import date as date_type
        from app.models.reports import OvertimeRequest
        from app.services.holidays import HolidayService

        holiday_svc = HolidayService(self.db, self.current_user)
        if await holiday_svc.is_holiday_today(getattr(self.current_user, "holiday_country", None)):
            approved = (await self.db.execute(
                select(OvertimeRequest).where(
                    OvertimeRequest.user_id == self.current_user.id,
                    OvertimeRequest.requested_date == date_type.today(),
                    OvertimeRequest.status == "approved",
                )
            )).scalar_one_or_none()
            if approved is None:
                raise HTTPException(
                    status_code=409,
                    detail="Today is a holiday. Check-in is only available with approved overtime for today — use the Overtime page instead.",
                )

        # Auto-detect outside-desk-area by comparing against the user's
        # saved DeskLocation -- radius now actually reads the Owner's
        # configured "Geofence radius (m)" setting (Attendance settings),
        # instead of being a hardcoded constant that ignored it entirely.
        outside_desk = False
        if lat is not None and lng is not None:
            desk = await self._desk_location(self.current_user.id)
            if desk is not None:
                from app.models.company import CompanySettings
                attendance_settings_row = (await self.db.execute(
                    select(CompanySettings).where(
                        CompanySettings.company_id == self.current_user.company_id,
                        CompanySettings.section == "attendance",
                    )
                )).scalar_one_or_none()
                radius = (
                    attendance_settings_row.data_json.get("default_geofence_radius_m", DEFAULT_DESK_AREA_RADIUS_METERS)
                    if attendance_settings_row else DEFAULT_DESK_AREA_RADIUS_METERS
                )
                distance = _distance_meters(lat, lng, desk.lat, desk.lng)
                outside_desk = distance > radius

        # New: compute how late this check-in is, right now, and store it on
        # the session -- not blocking, just recorded so the mobile app can
        # show "X minutes late" immediately, and the dashboard/AI analysis
        # can reference it later. Not late if there's no shift info to
        # compare against, or it comes back before the shift start. Skipped
        # entirely for part-time -- "late" doesn't conceptually apply to
        # flexible hours with no fixed shift start to compare against.
        late_minutes = None
        if not is_part_time:
            try:
                from zoneinfo import ZoneInfo
                from app.models.company import Company
                from app.core.worktime import compute_shift_bounds_utc

                company = await self.db.get(Company, self.current_user.company_id)
                employee_tz_name = getattr(self.current_user, "timezone", None) or company.timezone
                shift_start_utc, _ = compute_shift_bounds_utc(
                    company.working_hours_start, company.working_hours_end,
                    company.timezone, employee_tz_name, company.working_hours_mode,
                )
                now = datetime.now(timezone.utc)
                if now > shift_start_utc:
                    late_minutes = int((now - shift_start_utc).total_seconds() / 60)
            except Exception:
                pass  # never let shift-time math block a check-in

        session = AttendanceSession(
            user_id=self.current_user.id, desk_lat=lat, desk_lng=lng, checked_in_outside_desk=outside_desk,
            late_minutes=late_minutes,
        )
        self.db.add(session)
        await self.db.flush()

        # Fire the one-time "how did you sleep" prompt right at check-in --
        # tracked the same way as the 2h water/mood prompts (see
        # health_reminders.py), so it shows up in the Health tab and gates
        # report submission the same way.
        from app.models.misc import HealthCheckinPrompt
        from app.services import notifications as notification_service

        prompt = HealthCheckinPrompt(
            company_id=self.current_user.company_id,
            user_id=self.current_user.id,
            type="sleep_checkin",
        )
        self.db.add(prompt)
        await self.db.flush()
        await notification_service.send(
            self.db, self.current_user.id, category="health",
            title_key="health.sleepCheckin.title",
            body_key="health.sleepCheckin.body",
            extra_data={"type": "sleep_checkin", "prompt_id": str(prompt.id)},
        )

        # Attached directly onto the session object (not persisted -- just
        # set on the in-memory instance) so the response includes it
        # without needing a schema change beyond adding the field. Lets the
        # mobile app navigate straight to the sleep question immediately,
        # rather than depending on the push notification being tapped.
        session.sleep_prompt_id = prompt.id

        return session

    async def _deductions_enabled(self) -> bool:
        """New Settings toggle (Attendance section): 'Late/no-response
        deduction enabled'. When off, neither late minutes nor presence-check
        no-response penalties reduce credited hours -- only break time is
        ever excluded (that's not a penalty, it's just not-working time)."""
        from app.models.company import CompanySettings
        row = (await self.db.execute(select(CompanySettings).where(
            CompanySettings.company_id == self.current_user.company_id,
            CompanySettings.section == "attendance",
        ))).scalar_one_or_none()
        if row is None:
            return True
        return bool(row.data_json.get("late_no_response_deduction_enabled", True))

    async def today_invoice(self) -> dict:
        """Full breakdown for the checkout invoice dialog. These are
        deliberately the ONLY two deduction sources that exist anywhere in
        this system -- late arrival, and unanswered presence checks
        ("no response"). Nothing else ever reduces credited time. Break
        time is shown separately since it isn't a penalty, just legitimate
        non-work time."""
        session = await self._open_session(self.current_user.id)
        if session is None:
            return {
                "scheduled_minutes": 0, "elapsed_minutes": 0, "break_minutes": 0,
                "late_minutes": 0, "no_response_minutes": 0, "credited_minutes": 0,
                "deductions_enabled": await self._deductions_enabled(),
            }

        now = datetime.now(timezone.utc)
        check_in = session.check_in_at if session.check_in_at.tzinfo else session.check_in_at.replace(tzinfo=timezone.utc)
        elapsed_minutes = int((now - check_in).total_seconds() / 60)

        from app.models.attendance import BreakSession
        from math import ceil
        breaks = (await self.db.execute(
            select(BreakSession).where(BreakSession.attendance_session_id == session.id)
        )).scalars().all()
        break_minutes = 0
        for br in breaks:
            end = br.end_at or now
            seconds = (end - br.start_at).total_seconds()
            break_minutes += max(1, ceil(seconds / 60)) if seconds > 0 else 0

        deductions_enabled = await self._deductions_enabled()
        # Late minutes is shown for CONTEXT only, not subtracted here --
        # elapsed_minutes already only counts from the actual (late)
        # check-in time onward, so being late already naturally reduces
        # elapsed time. Subtracting late_minutes again here would penalize
        # the same lateness twice. Since it's context, not a deduction, it's
        # always shown regardless of the toggle -- only no_response_minutes
        # is actually gated by it now.
        late_minutes = session.late_minutes or 0
        no_response_minutes = (await self.deducted_minutes_today(self.current_user.id)) if deductions_enabled else 0

        credited = max(0, elapsed_minutes - break_minutes - no_response_minutes)

        # Scheduled shift length, for context in the invoice ("you were
        # scheduled for 9h, here's what happened to bring it down to X").
        from app.models.company import Company
        from app.core.worktime import compute_shift_bounds_utc
        company = await self._company_row()
        employee_tz_name = getattr(self.current_user, "timezone", None) or company.timezone
        shift_start_utc, shift_end_utc = compute_shift_bounds_utc(
            company.working_hours_start, company.working_hours_end,
            company.timezone, employee_tz_name, company.working_hours_mode,
        )
        scheduled_minutes = int((shift_end_utc - shift_start_utc).total_seconds() / 60)

        return {
            "scheduled_minutes": scheduled_minutes,
            "elapsed_minutes": elapsed_minutes,
            "break_minutes": break_minutes,
            "late_minutes": late_minutes,
            "no_response_minutes": no_response_minutes,
            "credited_minutes": credited,
            "deductions_enabled": deductions_enabled,
        }

    async def _company_row(self):
        from app.models.company import Company
        return await self.db.get(Company, self.current_user.company_id)

    async def actual_working_minutes_today(self) -> int:
        """(now - check_in_at) minus break time, minus late minutes, minus
        presence-check no-response penalties -- gated by the
        late_no_response_deduction_enabled setting. This is the ceiling
        used by the report form (checkout mode) and the "credited_minutes"
        figure in today_invoice() -- both now compute this identically, one
        source of truth."""
        invoice = await self.today_invoice()
        return invoice["credited_minutes"]

    async def check_out(self) -> AttendanceSession:
        session = await self._open_session(self.current_user.id)
        if session is None:
            raise HTTPException(status_code=409, detail="Not checked in")

        # New: check-out requires a report already submitted for today --
        # the mobile app shows the report form (with actual working hours
        # displayed) before ever calling this endpoint, but this is the
        # server-side backstop so it can't be bypassed.
        from datetime import date as date_type
        from app.models.reports import Report
        today_report = (await self.db.execute(
            select(Report).where(Report.user_id == self.current_user.id, Report.report_date == date_type.today())
        )).scalars().first()
        if today_report is None:
            raise HTTPException(
                status_code=409,
                detail="Submit today's report before checking out.",
            )

        # Auto-close any break still running when checking out -- don't
        # leave a dangling open break behind.
        from app.models.attendance import BreakSession
        open_break = (await self.db.execute(
            select(BreakSession).where(
                BreakSession.attendance_session_id == session.id, BreakSession.end_at.is_(None),
            )
        )).scalar_one_or_none()
        if open_break is not None:
            open_break.end_at = datetime.now(timezone.utc)

        # New: auto-close any still-active "working outside today" override
        # on checkout -- previously this only ever got deactivated by the
        # employee explicitly tapping "Back to desk" first. If they instead
        # just checked out directly without doing that, the override stayed
        # active indefinitely, showing "still outside" on the dashboard even
        # though the whole workday (and the override's relevance) is over.
        from app.models.attendance import WorkOutsideOverride
        today = datetime.now(timezone.utc).date()
        active_override = (await self.db.execute(
            select(WorkOutsideOverride).where(
                WorkOutsideOverride.user_id == self.current_user.id,
                WorkOutsideOverride.date == today,
                WorkOutsideOverride.active.is_(True),
            )
        )).scalar_one_or_none()
        if active_override is not None:
            active_override.active = False
            active_override.ended_at = datetime.now(timezone.utc)

        # New: compute how early this checkout is, relative to the
        # scheduled shift end -- not blocking, just recorded (dashboard
        # visibility + AI analysis input). Skipped for part-time -- "early"
        # doesn't conceptually apply with no fixed shift end to compare
        # against.
        early_checkout_minutes = None
        if getattr(self.current_user, "job_type", "full_time") != "part_time":
            try:
                from zoneinfo import ZoneInfo
                from app.models.company import Company
                from app.core.worktime import compute_shift_bounds_utc

                company = await self.db.get(Company, self.current_user.company_id)
                employee_tz_name = getattr(self.current_user, "timezone", None) or company.timezone
                _, shift_end_utc = compute_shift_bounds_utc(
                    company.working_hours_start, company.working_hours_end,
                    company.timezone, employee_tz_name, company.working_hours_mode,
                )
                now = datetime.now(timezone.utc)
                if now < shift_end_utc:
                    early_checkout_minutes = int((shift_end_utc - now).total_seconds() / 60)
            except Exception:
                pass

        session.check_out_at = datetime.now(timezone.utc)
        session.early_checkout_minutes = early_checkout_minutes
        await self.db.flush()
        return session

    async def start_break(self) -> "BreakSession":
        from app.models.attendance import BreakSession
        session = await self._open_session(self.current_user.id)
        if session is None:
            raise HTTPException(status_code=409, detail="You must be checked in to start a break")
        existing = (await self.db.execute(
            select(BreakSession).where(
                BreakSession.attendance_session_id == session.id, BreakSession.end_at.is_(None),
            )
        )).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="A break is already in progress")
        br = BreakSession(attendance_session_id=session.id)
        self.db.add(br)
        await self.db.flush()
        return br

    async def end_break(self) -> "BreakSession":
        from app.models.attendance import BreakSession
        session = await self._open_session(self.current_user.id)
        if session is None:
            raise HTTPException(status_code=409, detail="Not checked in")
        br = (await self.db.execute(
            select(BreakSession).where(
                BreakSession.attendance_session_id == session.id, BreakSession.end_at.is_(None),
            )
        )).scalar_one_or_none()
        if br is None:
            raise HTTPException(status_code=409, detail="No break is currently in progress")
        br.end_at = datetime.now(timezone.utc)
        await self.db.flush()
        return br

    async def record_ping(self, lat: float, lng: float) -> LocationPing:
        """BUSINESS RULE 1: no location ping accepted outside check-in..check-out."""
        session = await self._open_session(self.current_user.id)
        if session is None:
            raise HTTPException(
                status_code=409,
                detail="Location tracking is only active between check-in and check-out",
            )
        ping = LocationPing(attendance_session_id=session.id, lat=lat, lng=lng)
        self.db.add(ping)
        await self.db.flush()
        return ping

    async def send_manual_presence_check(self, employee_id: int) -> "PresenceCheckPrompt":
        """New: presence checks are now entirely MANUAL, sent by an Owner/
        Manager clicking a button for any specific employee they suspect
        needs one -- works whether that employee is marked "working
        outside today" or just checked in normally at their desk but has
        been flagged far away for a while (Location History's geofence
        indicator). No longer restricted to working-outside sessions only,
        and no longer sent automatically."""
        from app.models.attendance import PresenceCheckPrompt
        from app.services import notifications as notification_service

        target = await self.assert_user_in_tenant(employee_id)
        if not self.can_view_employee(target):
            raise HTTPException(status_code=403, detail="Not allowed for this employee")

        session = await self._open_session(employee_id)
        if session is None:
            raise HTTPException(status_code=409, detail="This employee isn't currently checked in")

        prompt = PresenceCheckPrompt(
            company_id=self.current_user.company_id, user_id=employee_id,
            attendance_session_id=session.id, sent_at=datetime.now(timezone.utc),
        )
        self.db.add(prompt)
        await self.db.flush()

        await notification_service.send(
            self.db, employee_id, category="attendance",
            title_key="attendance.presenceCheck.title",
            body_key="attendance.presenceCheck.body",
            extra_data={"type": "presence_check", "prompt_id": str(prompt.id)},
        )
        return prompt

    async def set_desk_location(self, lat: float, lng: float) -> DeskLocation:
        loc = DeskLocation(user_id=self.current_user.id, lat=lat, lng=lng)
        self.db.add(loc)
        await self.db.flush()
        return loc

    async def request_desk_location_change(self, lat: float, lng: float) -> "DeskLocationRequest":
        """New: desk location changes now go through approval rather than
        applying immediately. Notifies Owner/Manager so it shows up on
        their dashboard notification bell, clicking through to this
        employee's detail page."""
        from app.models.attendance import DeskLocationRequest
        from app.models.users import User
        from app.services import notifications as notification_service

        req = DeskLocationRequest(
            company_id=self.current_user.company_id, user_id=self.current_user.id,
            lat=lat, lng=lng, status="pending",
        )
        self.db.add(req)
        await self.db.flush()

        recipients = (await self.db.execute(
            select(User).where(
                User.company_id == self.current_user.company_id,
                User.role.in_(("owner_admin", "manager")),
                User.active.is_(True),
            )
        )).scalars().all()
        for recipient in recipients:
            # Manager only gets notified for their own team's employee.
            if recipient.role == "manager" and recipient.team_id != self.current_user.team_id:
                continue
            await notification_service.send(
                self.db, recipient.id, category="attendance",
                title_key="attendance.deskLocationRequest.title",
                body_key="attendance.deskLocationRequest.body",
                body_params={"name": self.current_user.full_name or "An employee"},
                extra_data={"type": "desk_location_request", "employee_id": str(self.current_user.id),
                           "request_id": str(req.id)},
                audience="dashboard",
            )
        return req

    async def my_desk_location_history(self) -> dict:
        """Employee-facing: their own confirmed history + their own pending/
        recently-decided requests."""
        from app.models.attendance import DeskLocationRequest

        history = (await self.db.execute(
            select(DeskLocation).where(DeskLocation.user_id == self.current_user.id)
            .order_by(DeskLocation.set_at.desc())
        )).scalars().all()
        requests = (await self.db.execute(
            select(DeskLocationRequest).where(DeskLocationRequest.user_id == self.current_user.id)
            .order_by(DeskLocationRequest.created_at.desc()).limit(20)
        )).scalars().all()
        return {
            "history": [{"id": h.id, "lat": h.lat, "lng": h.lng, "set_at": h.set_at} for h in history],
            "requests": [{"id": r.id, "lat": r.lat, "lng": r.lng, "status": r.status,
                         "created_at": r.created_at, "decided_at": r.decided_at} for r in requests],
        }

    async def desk_location_for_dashboard(self, employee_id: int) -> dict:
        """Dashboard-facing: one employee's full history + any pending
        requests, for the Employee Detail page's Desk Location tab."""
        from app.models.attendance import DeskLocationRequest

        target = await self.assert_user_in_tenant(employee_id)
        if not self.can_view_employee(target):
            raise HTTPException(status_code=403, detail="Not allowed for this employee")

        history = (await self.db.execute(
            select(DeskLocation).where(DeskLocation.user_id == employee_id)
            .order_by(DeskLocation.set_at.desc())
        )).scalars().all()
        requests = (await self.db.execute(
            select(DeskLocationRequest).where(DeskLocationRequest.user_id == employee_id)
            .order_by(DeskLocationRequest.created_at.desc()).limit(50)
        )).scalars().all()
        return {
            "history": [{"id": h.id, "lat": h.lat, "lng": h.lng, "set_at": h.set_at} for h in history],
            "requests": [{"id": r.id, "lat": r.lat, "lng": r.lng, "status": r.status,
                         "created_at": r.created_at, "decided_at": r.decided_at,
                         "decided_by": r.decided_by} for r in requests],
        }

    async def decide_desk_location_request(self, request_id: int, status: str) -> "DeskLocationRequest":
        from app.models.attendance import DeskLocationRequest
        from app.services import notifications as notification_service

        req = await self.db.get(DeskLocationRequest, request_id)
        if req is None or req.company_id != self.current_user.company_id:
            raise HTTPException(status_code=404, detail="Request not found")
        if req.status != "pending":
            raise HTTPException(status_code=409, detail="This request has already been decided")

        target = await self.assert_user_in_tenant(req.user_id)
        if not self.can_view_employee(target):
            raise HTTPException(status_code=403, detail="Not allowed for this employee")

        if status not in ("approved", "rejected"):
            raise HTTPException(status_code=400, detail="Invalid status")

        req.status = status
        req.decided_by = self.current_user.id
        req.decided_at = datetime.now(timezone.utc)

        if status == "approved":
            new_loc = DeskLocation(user_id=req.user_id, lat=req.lat, lng=req.lng)
            self.db.add(new_loc)

        await self.db.flush()

        # New: notify the employee of the decision -- previously the
        # request just silently changed status with no signal back to
        # them at all, so they'd only find out by manually reopening the
        # Desk Location screen and checking.
        await notification_service.send(
            self.db, req.user_id, category="attendance",
            title="Desk location update " + ("approved" if status == "approved" else "not approved"),
            body=(
                "Your desk location update was approved and is now active."
                if status == "approved"
                else "Your desk location update request was not approved."
            ),
            extra_data={"type": "desk_location_decision", "request_id": str(req.id), "status": status},
        )

        return req

    async def cancel_work_outside(self) -> None:
        """Turns off "working outside today" -- reverts back to normal
        desk-location tracking (and stops presence-check pings) for the
        rest of today."""
        from app.models.attendance import WorkOutsideOverride
        today = datetime.now(timezone.utc).date()
        override = (await self.db.execute(
            select(WorkOutsideOverride).where(
                WorkOutsideOverride.user_id == self.current_user.id,
                WorkOutsideOverride.date == today,
                WorkOutsideOverride.active.is_(True),
            )
        )).scalar_one_or_none()
        if override is None:
            raise HTTPException(status_code=409, detail="You're not currently marked as working outside today")
        override.active = False
        override.ended_at = datetime.now(timezone.utc)
        await self.db.flush()

    async def is_working_outside_today(self) -> bool:
        from app.models.attendance import WorkOutsideOverride
        today = datetime.now(timezone.utc).date()
        override = (await self.db.execute(
            select(WorkOutsideOverride).where(
                WorkOutsideOverride.user_id == self.current_user.id,
                WorkOutsideOverride.date == today,
                WorkOutsideOverride.active.is_(True),
            )
        )).scalar_one_or_none()
        return override is not None

    async def work_outside_available(self) -> bool:
        """Same checks as the /work-outside endpoint itself (allowed at all,
        and this user's role is permitted) -- exposed ahead of time so the
        mobile app can hide the button entirely instead of showing it and
        letting the request fail after the employee's already filled in a
        reason."""
        from app.models.company import CompanySettings
        row = (await self.db.execute(
            select(CompanySettings).where(
                CompanySettings.company_id == self.current_user.company_id,
                CompanySettings.section == "attendance",
            )
        )).scalar_one_or_none()
        settings_data = row.data_json if row else {}

        if not settings_data.get("allow_work_outside_override", True):
            return False

        raw_roles = settings_data.get("work_outside_override_roles")
        if isinstance(raw_roles, list):
            allowed_roles = {str(r).strip() for r in raw_roles if str(r).strip()}
        elif raw_roles:
            allowed_roles = {r.strip() for r in str(raw_roles).split(",") if r.strip()}
        else:
            allowed_roles = set()
        if allowed_roles and self.current_user.role not in allowed_roles:
            return False

        return True

    async def report_submitted_today(self) -> bool:
        """Uses the SAME mode-aware anchor timezone as
        ReportService.create_reports() actually saves report_date with
        (company timezone in "company_timezone" mode, the employee's own
        timezone in "local_wall_clock" mode) -- previously always used the
        company's timezone unconditionally, which could disagree with the
        employee's own personal "today" once their local calendar date had
        diverged from the company's (e.g. company in JST, employee in
        Vietnam -- JST rolls over to the next day 2 hours before Vietnam
        does), silently letting them check in again for a day they'd
        already submitted a report for, or vice versa."""
        from zoneinfo import ZoneInfo
        from app.models.company import Company
        from app.models.reports import Report

        company = await self.db.get(Company, self.current_user.company_id)
        mode = getattr(company, "working_hours_mode", "company_timezone")
        employee_tz_name = getattr(self.current_user, "timezone", None)
        anchor_name = company.timezone if mode == "company_timezone" else (employee_tz_name or company.timezone)
        try:
            tz = ZoneInfo(anchor_name or "UTC")
        except Exception:
            tz = ZoneInfo("UTC")
        today_local = datetime.now(tz).date()

        report = (await self.db.execute(
            select(Report).where(Report.user_id == self.current_user.id, Report.report_date == today_local)
        )).scalars().first()
        return report is not None

    async def my_status(self) -> dict:
        from math import ceil
        from app.models.attendance import PresenceCheckPrompt

        session = await self._open_session(self.current_user.id)
        on_break = False
        break_started_at = None
        total_break_minutes = 0
        if session is not None:
            from app.models.attendance import BreakSession
            breaks = (await self.db.execute(
                select(BreakSession).where(BreakSession.attendance_session_id == session.id)
            )).scalars().all()
            for br in breaks:
                if br.end_at is None:
                    on_break = True
                    break_started_at = br.start_at
                else:
                    # ceil, not int-truncate -- a 30-second test break
                    # should show as "1 min", not silently round down to 0
                    # and disappear from the total entirely.
                    seconds = (br.end_at - br.start_at).total_seconds()
                    total_break_minutes += max(1, ceil(seconds / 60)) if seconds > 0 else 0
        deducted_minutes = await self.deducted_minutes_today(self.current_user.id)
        working_outside = await self.is_working_outside_today()
        actual_working_minutes = await self.actual_working_minutes_today()
        outside_available = await self.work_outside_available()
        report_submitted = await self.report_submitted_today()

        # New: any unanswered presence check right now -- lets the Today
        # page show its blocking dialog based on a real, persisted state
        # check (polled the same way everything else here is), rather than
        # relying only on a transient push-message event that's lost the
        # moment the page reloads. Whatever's unanswered here shows again
        # on every load/poll until it's actually answered.
        pending_prompt = (await self.db.execute(
            select(PresenceCheckPrompt).where(
                PresenceCheckPrompt.user_id == self.current_user.id,
                PresenceCheckPrompt.responded_at.is_(None),
            ).order_by(PresenceCheckPrompt.sent_at.desc()).limit(1)
        )).scalar_one_or_none()

        return {
            "checked_in": session is not None,
            "session_id": session.id if session else None,
            "check_in_at": session.check_in_at if session else None,
            "checked_in_outside_desk": session.checked_in_outside_desk if session else False,
            "late_minutes": session.late_minutes if session else None,
            "on_break": on_break,
            "break_started_at": break_started_at,
            "total_break_minutes_today": total_break_minutes,
            "deducted_minutes_today": deducted_minutes,
            "working_outside_today": working_outside,
            "actual_working_minutes_today": actual_working_minutes,
            "work_outside_available": outside_available,
            "report_submitted_today": report_submitted,
            "pending_presence_check_id": pending_prompt.id if pending_prompt else None,
        }

    async def shift_status(self) -> dict:
        """Powers the mobile home screen: local shift start/end (already
        converted to the employee's own timezone for display), late status,
        and countdowns to shift start/end. Uses `getattr(user, "timezone",
        None)` defensively -- falls back to the company's timezone if the
        User model doesn't have this field yet."""
        from datetime import datetime, timezone as dt_timezone
        from zoneinfo import ZoneInfo
        from app.models.company import Company
        from app.core.worktime import compute_shift_bounds_utc

        company = await self.db.get(Company, self.current_user.company_id)
        employee_tz_name = getattr(self.current_user, "timezone", None) or company.timezone

        start_utc, end_utc = compute_shift_bounds_utc(
            company.working_hours_start, company.working_hours_end,
            company.timezone, employee_tz_name, company.working_hours_mode,
        )
        now = datetime.now(dt_timezone.utc)
        session = await self._open_session(self.current_user.id)

        is_late = None
        minutes_late = None
        if session is not None:
            check_in = session.check_in_at if session.check_in_at.tzinfo else session.check_in_at.replace(tzinfo=dt_timezone.utc)
            is_late = check_in > start_utc
            if is_late:
                minutes_late = int((check_in - start_utc).total_seconds() / 60)

        minutes_until_start = int((start_utc - now).total_seconds() / 60) if now < start_utc else None
        minutes_until_end = int((end_utc - now).total_seconds() / 60) if session is not None and now < end_utc else None
        # New: whether today's whole shift window has already closed --
        # computed regardless of check-in status (unlike minutes_until_end
        # above, which only exists once already checked in). Powers the
        # mobile "check-in disabled, shift already ended" state.
        shift_has_ended = now > end_utc

        employee_tz = ZoneInfo(employee_tz_name)
        return {
            "shift_start_local": start_utc.astimezone(employee_tz).strftime("%H:%M"),
            "shift_end_local": end_utc.astimezone(employee_tz).strftime("%H:%M"),
            "employee_timezone": employee_tz_name,
            "working_hours_mode": company.working_hours_mode,
            "is_late": is_late,
            "minutes_late": minutes_late,
            "minutes_until_start": minutes_until_start,
            "shift_has_ended": shift_has_ended,
            "minutes_until_end": minutes_until_end,
            # New: lets mobile/portal decide whether to show the shift
            # clock/countdown UI at all -- part-time employees have no
            # fixed shift to count down to, so these numbers above are
            # still technically computed (using the company's default
            # working hours as a fallback) but meaningless for them.
            "job_type": getattr(self.current_user, "job_type", "full_time"),
        }

    async def my_history(self, limit: int = 60) -> list[AttendanceSession]:
        res = await self.db.execute(
            select(AttendanceSession)
            .where(AttendanceSession.user_id == self.current_user.id)
            .order_by(AttendanceSession.check_in_at.desc())
            .limit(limit)
        )
        return list(res.scalars())

    # -------- dashboard side (owner/manager) --------
    async def logs(self, employee_id: int | None) -> list[dict]:
        """New: each row now includes `report_id` -- the daily Report
        matching that session's local check-in date, if one exists (only
        set once the employee actually submits a report, same as the
        checkout gate). Batch-looked-up in one extra query rather than one
        query per session, to avoid N+1 across up to 500 rows."""
        from zoneinfo import ZoneInfo
        from app.models.company import Company
        from app.models.reports import Report
        from app.models.users import User

        stmt = self.tenant_select_via_user(AttendanceSession).order_by(AttendanceSession.check_in_at.desc()).limit(500)
        if employee_id is not None:
            target = await self.assert_user_in_tenant(employee_id)
            if not self.can_view_employee(target):
                raise HTTPException(status_code=403, detail="Not allowed for this employee")
            stmt = stmt.where(AttendanceSession.user_id == employee_id)
        sessions = list((await self.db.execute(stmt)).scalars())
        if not sessions:
            return []

        company = await self.db.get(Company, self.company_id)
        user_ids = {s.user_id for s in sessions}
        user_tz_map = {
            u.id: (getattr(u, "timezone", None) or company.timezone)
            for u in (await self.db.execute(select(User).where(User.id.in_(user_ids)))).scalars()
        }

        # (user_id, local_date) -> session's local check-in date, computed
        # once per session so the batch report lookup below can match on
        # exactly the same dates.
        session_local_dates = {}
        for s in sessions:
            tz = ZoneInfo(user_tz_map.get(s.user_id) or company.timezone or "UTC")
            check_in = s.check_in_at if s.check_in_at.tzinfo else s.check_in_at.replace(tzinfo=timezone.utc)
            session_local_dates[s.id] = check_in.astimezone(tz).date()

        relevant_dates = set(session_local_dates.values())
        report_rows = (await self.db.execute(
            select(Report.id, Report.user_id, Report.report_date).where(
                Report.user_id.in_(user_ids), Report.report_date.in_(relevant_dates),
            )
        )).all()
        report_by_user_date = {(user_id, report_date): report_id for report_id, user_id, report_date in report_rows}

        return [
            {
                "id": s.id, "user_id": s.user_id, "check_in_at": s.check_in_at, "check_out_at": s.check_out_at,
                "checked_in_outside_desk": s.checked_in_outside_desk, "late_minutes": s.late_minutes,
                "early_checkout_minutes": s.early_checkout_minutes,
                "report_id": report_by_user_date.get((s.user_id, session_local_dates[s.id])),
            }
            for s in sessions
        ]

    async def working_outside_today(self) -> list[dict]:
        """Dashboard-facing: today's confirmed work-outside overrides
        (active or already ended), with employee names, stated reason, and
        start/end times. Manager sees own team only."""
        from app.models.attendance import WorkOutsideOverride
        from app.models.users import User

        today = datetime.now(timezone.utc).date()
        stmt = (
            select(WorkOutsideOverride, User.full_name)
            .join(User, User.id == WorkOutsideOverride.user_id)
            .where(
                User.company_id == self.current_user.company_id,
                WorkOutsideOverride.date == today,
            )
        )
        if self.current_user.role == "manager":
            stmt = stmt.where(User.team_id == self.current_user.team_id)
        rows = (await self.db.execute(stmt)).all()
        return [
            {"user_id": row.user_id, "employee_name": full_name,
             "reason": row.reason, "date": str(row.date),
             "started_at": row.created_at, "ended_at": row.ended_at, "active": row.active}
            for row, full_name in rows
        ]

    async def respond_presence_check(self, prompt_id: int, response: str) -> "PresenceCheckPrompt":
        from datetime import timezone as dt_timezone
        from app.models.attendance import PresenceCheckPrompt

        prompt = await self.db.get(PresenceCheckPrompt, prompt_id)
        if prompt is None or prompt.user_id != self.current_user.id:
            raise HTTPException(status_code=404, detail="Presence check not found")
        if prompt.responded_at is not None:
            return prompt  # already answered, idempotent
        prompt.responded_at = datetime.now(dt_timezone.utc)
        prompt.response = response
        # Answered in time -- even if it landed right at the edge, honor a
        # response that arrives before the 10-min deduction sweep catches
        # it (the sweep only marks *unanswered* prompts as deducted).
        await self.db.flush()

        # "No, not okay" gets flagged to the manager immediately -- this
        # isn't a routine attendance ping at that point, it's someone
        # telling the system something is wrong. Only if this alert type
        # is actually enabled -- previously created unconditionally,
        # ignoring the company's own AlertSetting toggle for it.
        if response == "no":
            from app.models.misc import Alert, AlertSetting
            alert_setting = (await self.db.execute(
                select(AlertSetting).where(
                    AlertSetting.company_id == self.current_user.company_id,
                    AlertSetting.type == "presence_check_not_okay",
                )
            )).scalar_one_or_none()
            if alert_setting is None or alert_setting.enabled:
                alert = Alert(company_id=self.current_user.company_id, user_id=self.current_user.id,
                              type="presence_check_not_okay", status="open")
                self.db.add(alert)
                await self.db.flush()

        return prompt

    async def revert_presence_deduction(self, prompt_id: int) -> "PresenceCheckPrompt":
        from app.models.attendance import PresenceCheckPrompt

        prompt = await self.db.get(PresenceCheckPrompt, prompt_id)
        if prompt is None or prompt.company_id != self.current_user.company_id:
            raise HTTPException(status_code=404, detail="Presence check not found")
        if not prompt.deducted:
            raise HTTPException(status_code=400, detail="This wasn't deducted, nothing to revert")
        prompt.deducted = False
        prompt.reverted_by = self.current_user.id
        prompt.reverted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return prompt

    async def deducted_minutes_today(self, user_id: int) -> int:
        """Total minutes marked deducted today across all this user's
        presence-check prompts (each deducted prompt = its interval_minutes,
        currently 40 each). Used to compute "verified worked time" alongside
        break-time exclusion."""
        from app.models.attendance import PresenceCheckPrompt

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        rows = (await self.db.execute(
            select(PresenceCheckPrompt).where(
                PresenceCheckPrompt.user_id == user_id,
                PresenceCheckPrompt.deducted.is_(True),
                PresenceCheckPrompt.sent_at >= today_start,
            )
        )).scalars().all()
        return sum(p.interval_minutes for p in rows)

    async def presence_checks_for_dashboard(self, employee_id: int | None = None) -> list:
        from app.models.attendance import PresenceCheckPrompt

        stmt = self.tenant_select_via_user(PresenceCheckPrompt).order_by(PresenceCheckPrompt.sent_at.desc()).limit(200)
        if employee_id is not None:
            target = await self.assert_user_in_tenant(employee_id)
            if not self.can_view_employee(target):
                raise HTTPException(status_code=403, detail="Not allowed for this employee")
            stmt = stmt.where(PresenceCheckPrompt.user_id == employee_id)
        return list((await self.db.execute(stmt)).scalars())

    async def create_leave(self, type_: str, start, end, start_time: str | None = None, end_time: str | None = None) -> LeaveRequest:
        lr = LeaveRequest(
            user_id=self.current_user.id, type=type_, start_date=start, end_date=end,
            start_time=start_time, end_time=end_time,
        )
        self.db.add(lr)
        await self.db.flush()
        return lr