"""Daily reports. Enforces rule 4 (same-day edit window) at the service layer."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.company import Company
from app.models.reports import Project, Report, ReportComment
from app.services.base import TenantService


class ReportService(TenantService):
    async def _company_tz(self) -> ZoneInfo:
        company = await self.db.get(Company, self.company_id)
        try:
            return ZoneInfo(company.timezone or "UTC")
        except Exception:
            return ZoneInfo("UTC")

    async def _anchor_tz(self) -> ZoneInfo:
        """New: the SAME mode-aware anchor timezone compute_shift_bounds_utc()
        uses for shift start/end -- company timezone in "company_timezone"
        mode, the employee's own timezone (falling back to company's) in
        "local_wall_clock" mode. Previously report_date and the edit cutoff
        always used the company's timezone unconditionally, regardless of
        mode or the employee's own timezone -- for an employee whose
        personal "today" had already rolled over relative to the company's
        (e.g. company in JST, employee in Vietnam, ICT is 2h behind), this
        silently disagreed with what the employee actually experienced as
        "today," and with report_submitted_today()'s own date calculation,
        letting them submit (or appear not to have submitted) for the wrong
        calendar day entirely."""
        company = await self.db.get(Company, self.company_id)
        mode = getattr(company, "working_hours_mode", "company_timezone")
        employee_tz_name = getattr(self.current_user, "timezone", None)
        anchor_name = company.timezone if mode == "company_timezone" else (employee_tz_name or company.timezone)
        try:
            return ZoneInfo(anchor_name or "UTC")
        except Exception:
            return ZoneInfo("UTC")

    async def _local_midnight_cutoff(self, for_date: date) -> datetime:
        """editable_until = the next local midnight, in the SAME anchor
        timezone report_date itself is computed in (rule 4)."""
        tz = await self._anchor_tz()
        next_midnight_local = datetime.combine(for_date + timedelta(days=1), time.min, tzinfo=tz)
        return next_midnight_local.astimezone(timezone.utc)

    async def create_reports(self, entries: list) -> list[Report]:
        tz = await self._anchor_tz()
        today_local = datetime.now(tz).date()
        cutoff = await self._local_midnight_cutoff(today_local)

        # New: total reported hours today (existing rows + this new batch)
        # must not exceed actual working hours (check-in to now, minus
        # breaks) -- under-reporting is fine, over-reporting isn't. Reuses
        # AttendanceService's calculation rather than duplicating it.
        from app.services.attendance import AttendanceService
        attendance_svc = AttendanceService(self.db, self.current_user)
        actual_minutes = await attendance_svc.actual_working_minutes_today()
        actual_hours = actual_minutes / 60

        existing_hours = float(await self.db.scalar(
            select(func.coalesce(func.sum(Report.hours), 0)).where(
                Report.user_id == self.current_user.id, Report.report_date == today_local,
            )
        ) or 0)
        new_hours = sum(e.hours for e in entries)

        if existing_hours + new_hours > actual_hours + 0.01:  # small epsilon for float rounding
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Total reported hours ({existing_hours + new_hours:.1f}h) exceeds your actual "
                    f"working hours today ({actual_hours:.1f}h). Adjust your entries to fit within that."
                ),
            )

        created: list[Report] = []
        for e in entries:
            if e.project_id is not None:
                await self._assert_project_in_tenant(e.project_id)
            report = Report(
                user_id=self.current_user.id,
                project_id=e.project_id,
                hours=e.hours,
                summary=e.summary,
                report_date=today_local,
                editable_until=cutoff,
            )
            self.db.add(report)
            created.append(report)
        await self.db.flush()
        return created

    async def _get_own_editable(self, report_id: int) -> Report:
        report = await self.db.get(Report, report_id)
        if report is None or report.user_id != self.current_user.id:
            raise HTTPException(status_code=404, detail="Report not found")
        # BUSINESS RULE 4: locked after local midnight — server-enforced, not client.
        cutoff = report.editable_until
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= cutoff:
            raise HTTPException(status_code=403, detail="Report locked: same-day edit window has passed")
        return report

    async def update_report(self, report_id: int, patch) -> Report:
        report = await self._get_own_editable(report_id)
        if patch.project_id is not None:
            await self._assert_project_in_tenant(patch.project_id)
            report.project_id = patch.project_id
        if patch.hours is not None:
            report.hours = patch.hours
        if patch.summary is not None:
            report.summary = patch.summary
        await self.db.flush()
        return report

    async def delete_report(self, report_id: int) -> None:
        report = await self._get_own_editable(report_id)
        await self.db.delete(report)
        await self.db.flush()

    async def my_reports(self, limit: int = 100) -> list[Report]:
        res = await self.db.execute(
            select(Report).where(Report.user_id == self.current_user.id)
            .order_by(Report.report_date.desc(), Report.id.desc()).limit(limit)
        )
        return list(res.scalars())

    # -------- dashboard side --------
    async def list_reports(self, employee_id: int | None, project_id: int | None) -> list[Report]:
        stmt = self.tenant_select_via_user(Report).order_by(Report.report_date.desc()).limit(500)
        if employee_id is not None:
            target = await self.assert_user_in_tenant(employee_id)
            if not self.can_view_employee(target):
                raise HTTPException(status_code=403, detail="Not allowed for this employee")
            stmt = stmt.where(Report.user_id == employee_id)
        if project_id is not None:
            stmt = stmt.where(Report.project_id == project_id)
        return list((await self.db.execute(stmt)).scalars())

    async def comment(self, report_id: int, text: str) -> ReportComment:
        report = await self.db.get(Report, report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Report not found")
        author = await self.assert_user_in_tenant(report.user_id)  # tenant check via report owner
        if not self.can_view_employee(author):
            raise HTTPException(status_code=403, detail="Not allowed for this employee")
        rc = ReportComment(report_id=report_id, author_id=self.current_user.id, comment=text)
        self.db.add(rc)
        await self.db.flush()
        return rc

    async def _assert_project_in_tenant(self, project_id: int) -> Project:
        project = await self.db.get(Project, project_id)
        if project is None or project.company_id != self.company_id:
            raise HTTPException(status_code=404, detail="Project not found")
        # New: employees can only report against a project they're actually
        # assigned to -- the dropdown already only shows assigned projects,
        # but that's a UI convenience, not enforcement. This closes the
        # server-side gap (calling the API directly, or a stale client-side
        # project list after an assignment was removed) so an unassigned
        # report can never quietly skew a project's labor cost. Owner/
        # Manager stay unrestricted, matching list_projects()'s same rule.
        if self.current_user.role == "employee":
            from app.models.reports import ProjectAssignment
            assigned = await self.db.scalar(
                select(ProjectAssignment).where(
                    ProjectAssignment.project_id == project_id,
                    ProjectAssignment.user_id == self.current_user.id,
                )
            )
            if assigned is None:
                raise HTTPException(status_code=403, detail="You're not assigned to this project")
        return project

    async def list_projects(self, include_inactive: bool = False) -> list[Project]:
        stmt = self.tenant_select(Project)
        if not include_inactive:
            stmt = stmt.where(Project.active.is_(True))
        # New: employees only see projects they're explicitly assigned to.
        # Owner/Manager see everything, unrestricted -- they already manage
        # every other resource company-wide, and need to see all projects
        # to assign employees to them in the first place.
        if self.current_user.role == "employee":
            from app.models.reports import ProjectAssignment
            stmt = stmt.join(ProjectAssignment, ProjectAssignment.project_id == Project.id).where(
                ProjectAssignment.user_id == self.current_user.id
            )
        res = await self.db.execute(stmt)
        return list(res.scalars())