"""Overtime. Enforces rule 2: a session cannot be closed without a report.
Also enforces the NEW rule: a session cannot be STARTED without an approved
OvertimeRequest for today -- self-initiated instant-start no longer exists.
"""
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.models.reports import OvertimeRequest, OvertimeSession
from app.services.base import TenantService


class OvertimeService(TenantService):
    async def _anchor_tz_for(self, user) -> "ZoneInfo":
        """Shared mode-aware employee timezone anchor -- company timezone
        in "company_timezone" mode, the given user's own timezone
        (falling back to company's) in "local_wall_clock" mode. Same
        anchor logic used across attendance/reports for "today"; factored
        out here since it was duplicated inline in two places."""
        from zoneinfo import ZoneInfo
        from app.models.company import Company

        company = await self.db.get(Company, user.company_id)
        mode = getattr(company, "working_hours_mode", "company_timezone")
        employee_tz_name = getattr(user, "timezone", None)
        anchor_name = company.timezone if mode == "company_timezone" else (employee_tz_name or company.timezone)
        try:
            return ZoneInfo(anchor_name or "UTC")
        except Exception:
            return ZoneInfo("UTC")

    # ---------- requests ----------
    async def request_overtime(self, requested_date: date, planned_start_time: str,
                                planned_end_time: str, reason: str) -> OvertimeRequest:
        # New: planned_end_time <= planned_start_time is now VALID -- it
        # means the overtime spans into the next calendar day (e.g. 23:30
        # to 02:00). Previously this was rejected outright, making genuine
        # overnight overtime impossible to request at all. The only thing
        # still rejected is the exact same instant for both (zero-length),
        # which is never meaningful either way.
        if planned_start_time == planned_end_time:
            raise HTTPException(status_code=400, detail="Start and end time can't be identical")

        # New: block requesting overtime for a date that's already passed --
        # previously nothing checked this at all, so a date-picker mistake
        # (like picking the 20th instead of the 21st) could silently create
        # a request nobody could ever act on. Uses the employee's own
        # mode-aware "today" (same anchor as shift bounds/report_date), not
        # a bare server date, so this stays consistent with everything
        # else that computes "today" for this specific employee.
        tz = await self._anchor_tz_for(self.current_user)
        today_local = datetime.now(tz).date()

        if requested_date < today_local:
            raise HTTPException(status_code=400, detail="Can't request overtime for a date that's already passed")

        req = OvertimeRequest(
            user_id=self.current_user.id, requested_date=requested_date,
            planned_start_time=planned_start_time, planned_end_time=planned_end_time, reason=reason,
        )
        self.db.add(req)
        await self.db.flush()

        # New: notify Owner/Manager -- previously this created the request
        # entirely silently, with no signal on the dashboard at all that
        # anything needed a decision. Same pattern as desk-location
        # requests: manager only gets notified for their own team.
        from app.models.users import User
        from app.services import notifications as notification_service

        recipients = (await self.db.execute(
            select(User).where(
                User.company_id == self.current_user.company_id,
                User.role.in_(("owner_admin", "manager")),
                User.active.is_(True),
            )
        )).scalars().all()
        for recipient in recipients:
            if recipient.role == "manager" and recipient.team_id != self.current_user.team_id:
                continue
            await notification_service.send(
                self.db, recipient.id, category="overtime",
                title="Overtime request submitted",
                body=f"{self.current_user.full_name or 'An employee'} requested overtime for {requested_date}.",
                extra_data={"type": "overtime_request", "employee_id": str(self.current_user.id),
                           "request_id": str(req.id)},
                audience="dashboard",
            )

        return req

    async def my_requests(self, limit: int = 100) -> list[OvertimeRequest]:
        res = await self.db.execute(
            select(OvertimeRequest).where(OvertimeRequest.user_id == self.current_user.id)
            .order_by(OvertimeRequest.requested_date.desc()).limit(limit)
        )
        return list(res.scalars())

    async def list_requests_for_dashboard(self, employee_id: int | None = None) -> list[OvertimeRequest]:
        stmt = self.tenant_select_via_user(OvertimeRequest).order_by(OvertimeRequest.requested_date.desc()).limit(500)
        if employee_id is not None:
            target = await self.assert_user_in_tenant(employee_id)
            if not self.can_view_employee(target):
                raise HTTPException(status_code=403, detail="Not allowed for this employee")
            stmt = stmt.where(OvertimeRequest.user_id == employee_id)
        return list((await self.db.execute(stmt)).scalars())

    async def decide_request(self, request_id: int, status: str) -> OvertimeRequest:
        req = await self.db.get(OvertimeRequest, request_id)
        if req is None:
            raise HTTPException(status_code=404, detail="Overtime request not found")
        target = await self.assert_user_in_tenant(req.user_id)
        if not self.can_view_employee(target):
            raise HTTPException(status_code=403, detail="Not allowed for this employee")
        req.status = status
        req.decided_by = self.current_user.id
        req.decided_at = datetime.now(timezone.utc)
        await self.db.flush()

        # New: notify the employee of the decision -- previously silent,
        # same gap as desk-location requests had before that was fixed.
        from app.services import notifications as notification_service

        await notification_service.send(
            self.db, req.user_id, category="overtime",
            title="Overtime request " + ("approved" if status == "approved" else "not approved"),
            body=(
                f"Your overtime request for {req.requested_date} was approved."
                if status == "approved"
                else f"Your overtime request for {req.requested_date} was not approved."
            ),
            extra_data={"type": "overtime_decision", "request_id": str(req.id), "status": status},
        )

        return req

    async def _approved_request_for_today(self, user_id: int) -> OvertimeRequest | None:
        """Uses the SAME mode-aware employee-timezone anchor as
        request_overtime()'s past-date check and compute_shift_bounds_utc()
        -- previously used a bare datetime.now(timezone.utc).date(), which
        disagreed with the employee's own local calendar date whenever
        their timezone is ahead of UTC and it's early in their morning
        (e.g. 00:20 in Vietnam, UTC+7, is still the PREVIOUS day in UTC),
        silently returning None even for a genuinely approved request
        dated "today" in the employee's own terms."""
        from app.models.users import User

        user = await self.db.get(User, user_id)
        tz = await self._anchor_tz_for(user)
        today = datetime.now(tz).date()

        res = await self.db.execute(
            select(OvertimeRequest).where(
                OvertimeRequest.user_id == user_id,
                OvertimeRequest.requested_date == today,
                OvertimeRequest.status == "approved",
            ).limit(1)
        )
        return res.scalar_one_or_none()

    # ---------- sessions (start requires an approved request for today) ----------
    async def _open(self) -> OvertimeSession | None:
        res = await self.db.execute(
            select(OvertimeSession)
            .where(OvertimeSession.user_id == self.current_user.id, OvertimeSession.end_at.is_(None))
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def start(self, project_id: int | None) -> OvertimeSession:
        if await self._open():
            raise HTTPException(status_code=409, detail="Overtime session already running")
        approved = await self._approved_request_for_today(self.current_user.id)
        if approved is None:
            raise HTTPException(
                status_code=409,
                detail="No approved overtime request for today. Submit a request and wait for approval first.",
            )

        # New: block starting AGAIN off the same approved request once it's
        # already been used for a session -- previously only checked for a
        # currently OPEN session, so ending overtime and then starting a
        # second (or third...) session from the exact same single approval
        # was silently allowed. One approval grants exactly one session.
        already_used = (await self.db.execute(
            select(OvertimeSession).where(OvertimeSession.request_id == approved.id).limit(1)
        )).scalar_one_or_none()
        if already_used is not None:
            raise HTTPException(
                status_code=409,
                detail="This approved overtime request has already been used for a session today.",
            )

        # New: don't allow starting before the approved planned start time.
        # Evaluated in the employee's OWN timezone (falls back to the
        # company's if unset) -- same pattern as shift_status(), since
        # "now" has to mean "now for this specific person," not a naive
        # server clock or the company's timezone.
        from zoneinfo import ZoneInfo
        from app.models.company import Company

        company = await self.db.get(Company, self.current_user.company_id)
        employee_tz_name = getattr(self.current_user, "timezone", None) or company.timezone
        now_local = datetime.now(ZoneInfo(employee_tz_name))
        if now_local.strftime("%H:%M") < approved.planned_start_time:
            raise HTTPException(
                status_code=409,
                detail=f"It's not your overtime start time yet — your approved time is {approved.planned_start_time}.",
            )

        ot = OvertimeSession(
            user_id=self.current_user.id, project_id=project_id, initiated_by="self",
            reason=approved.reason, request_id=approved.id,
        )
        self.db.add(ot)
        await self.db.flush()
        return ot

    async def attach_report(self, ot_id: int, summary: str) -> OvertimeSession:
        ot = await self._get_own(ot_id)
        ot.summary = summary
        await self.db.flush()
        return ot

    async def end(self) -> OvertimeSession:
        """BUSINESS RULE 2 (platform-locked): end_at is only settable once a summary
        report is attached. Attempting to close early returns a clear 409."""
        ot = await self._open()
        if ot is None:
            raise HTTPException(status_code=409, detail="No running overtime session")
        if not ot.summary:
            raise HTTPException(
                status_code=409,
                detail="Overtime cannot be closed without a report. POST /overtime/{id}/report first.",
            )
        now = datetime.now(timezone.utc)
        ot.end_at = now
        start_at = ot.start_at if ot.start_at.tzinfo else ot.start_at.replace(tzinfo=timezone.utc)
        ot.hours = round((now - start_at).total_seconds() / 3600, 2)
        await self.db.flush()
        return ot

    async def _get_own(self, ot_id: int) -> OvertimeSession:
        ot = await self.db.get(OvertimeSession, ot_id)
        if ot is None or ot.user_id != self.current_user.id:
            raise HTTPException(status_code=404, detail="Overtime session not found")
        return ot

    async def get_one(self, overtime_id: int) -> OvertimeSession:
        """New: single-session detail, matching the same pattern as
        GET /reports/{report_id} -- the session's own author is always
        allowed to view it; anyone else goes through the normal tenant +
        can_view_employee checks."""
        ot = await self.db.get(OvertimeSession, overtime_id)
        if ot is None:
            raise HTTPException(status_code=404, detail="Overtime session not found")
        if ot.user_id != self.current_user.id:
            owner = await self.assert_user_in_tenant(ot.user_id)
            if not self.can_view_employee(owner):
                raise HTTPException(status_code=403, detail="Not allowed for this employee")
        return ot

    async def mine(self, limit: int = 20, offset: int = 0) -> list[OvertimeSession]:
        res = await self.db.execute(
            select(OvertimeSession).where(OvertimeSession.user_id == self.current_user.id)
            .order_by(OvertimeSession.start_at.desc()).limit(limit).offset(offset)
        )
        return list(res.scalars())

    async def list_for_dashboard(self, employee_id: int | None) -> list[OvertimeSession]:
        stmt = self.tenant_select_via_user(OvertimeSession).order_by(OvertimeSession.start_at.desc()).limit(500)
        if employee_id is not None:
            target = await self.assert_user_in_tenant(employee_id)
            if not self.can_view_employee(target):
                raise HTTPException(status_code=403, detail="Not allowed for this employee")
            stmt = stmt.where(OvertimeSession.user_id == employee_id)
        return list((await self.db.execute(stmt)).scalars())