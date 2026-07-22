"""Invoicing. Manually triggered (Owner clicks "Produce invoices for all"),
generated via a queued Celery task -- deliberately NOT auto-scheduled like
certificates. One invoice per (employee, pay period), covering the most
recently COMPLETED pay period relative to when it's generated.

Two calculation modes per employee (User.actual_working_hours):
  True  -- sums real clocked hours across every completed AttendanceSession
           in the period, applying the SAME deductions today_invoice()
           already uses per day (breaks excluded, presence-check
           no-response minutes deducted if the company has that enabled;
           late arrival is NOT double-deducted, same reasoning as
           today_invoice() -- it already naturally reduces elapsed time).
  False -- assumes the full scheduled shift length for every configured
           workday in the period, minus only the days covered by approved
           leave. Ignores clock-in precision entirely -- a salary-style
           calculation.
"""
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from math import ceil

from fastapi import HTTPException
from sqlalchemy import select

from app.models.attendance import AttendanceSession, BreakSession, LeaveRequest, PresenceCheckPrompt
from app.models.company import Company, CompanySettings
from app.models.misc import Invoice
from app.models.users import User
from app.services.base import TenantService

WEEKDAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _safe_day(year: int, month: int, day: int) -> int:
    """Clamps a target day-of-month to whatever that month actually has --
    e.g. pay_period_start_day=31 in a 30-day month becomes 30, not an error."""
    return min(day, monthrange(year, month)[1])


def compute_last_completed_period(pay_period_start_day: int, today: date) -> tuple[date, date]:
    """Given a company's pay_period_start_day (1-31), returns the most
    recently COMPLETED period's (start, end) -- e.g. start_day=25: periods
    run 25th-to-24th. If today is July 22, the last completed period is
    May 25 - June 24 (the period containing today, June 25 - July 24,
    hasn't finished yet)."""
    def period_start_on_or_before(d: date) -> date:
        day = _safe_day(d.year, d.month, pay_period_start_day)
        candidate = d.replace(day=day)
        if candidate <= d:
            return candidate
        prev_month_end = d.replace(day=1) - timedelta(days=1)
        return prev_month_end.replace(day=_safe_day(prev_month_end.year, prev_month_end.month, pay_period_start_day))

    current_period_start = period_start_on_or_before(today)
    last_period_end = current_period_start - timedelta(days=1)
    last_period_start = period_start_on_or_before(last_period_end)
    return last_period_start, last_period_end


class InvoiceService(TenantService):
    async def _invoicing_settings(self) -> dict:
        row = (await self.db.execute(select(CompanySettings).where(
            CompanySettings.company_id == self.company_id, CompanySettings.section == "invoicing",
        ))).scalar_one_or_none()
        return row.data_json if row else {}

    async def _deducted_minutes_in_range(self, user_id: int, start_dt: datetime, end_dt: datetime) -> int:
        """Same deduction source as today_invoice()'s no_response_minutes,
        generalized to an arbitrary date range instead of just today."""
        rows = (await self.db.execute(
            select(PresenceCheckPrompt).where(
                PresenceCheckPrompt.user_id == user_id,
                PresenceCheckPrompt.deducted.is_(True),
                PresenceCheckPrompt.sent_at >= start_dt,
                PresenceCheckPrompt.sent_at <= end_dt,
            )
        )).scalars().all()
        return sum(p.interval_minutes for p in rows)

    async def _actual_hours_for_period(self, user: User, period_start: date, period_end: date) -> float:
        period_start_dt = datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc)
        period_end_dt = datetime.combine(period_end, datetime.max.time(), tzinfo=timezone.utc)

        sessions = (await self.db.execute(
            select(AttendanceSession).where(
                AttendanceSession.user_id == user.id,
                AttendanceSession.check_out_at.is_not(None),
                AttendanceSession.check_in_at >= period_start_dt,
                AttendanceSession.check_in_at <= period_end_dt,
            )
        )).scalars().all()

        deductions_enabled_row = (await self.db.execute(select(CompanySettings).where(
            CompanySettings.company_id == self.company_id, CompanySettings.section == "attendance",
        ))).scalar_one_or_none()
        deductions_enabled = bool(
            deductions_enabled_row.data_json.get("late_no_response_deduction_enabled", True)
            if deductions_enabled_row else True
        )

        total_minutes = 0.0
        for session in sessions:
            check_in = session.check_in_at if session.check_in_at.tzinfo else session.check_in_at.replace(tzinfo=timezone.utc)
            check_out = session.check_out_at if session.check_out_at.tzinfo else session.check_out_at.replace(tzinfo=timezone.utc)
            elapsed_minutes = (check_out - check_in).total_seconds() / 60

            breaks = (await self.db.execute(
                select(BreakSession).where(BreakSession.attendance_session_id == session.id)
            )).scalars().all()
            break_minutes = 0
            for br in breaks:
                end = br.end_at or check_out
                seconds = (end - br.start_at).total_seconds()
                break_minutes += max(1, ceil(seconds / 60)) if seconds > 0 else 0

            no_response_minutes = (
                await self._deducted_minutes_in_range(user.id, check_in, check_out) if deductions_enabled else 0
            )

            total_minutes += max(0, elapsed_minutes - break_minutes - no_response_minutes)

        return round(total_minutes / 60, 2)

    async def _scheduled_hours_for_period(self, company: Company, user: User, period_start: date, period_end: date) -> float:
        """Salary-style: full scheduled shift length for every configured
        workday in the period, minus days covered by approved leave. Falls
        back to the company's own working hours even for part-time
        employees (who have no fixed shift) -- a reasonable default absent
        any other definition of "a scheduled day" for them."""
        from app.core.worktime import compute_shift_bounds_utc

        employee_tz_name = getattr(user, "timezone", None) or company.timezone
        shift_start_utc, shift_end_utc = compute_shift_bounds_utc(
            company.working_hours_start, company.working_hours_end,
            company.timezone, employee_tz_name, company.working_hours_mode,
        )
        scheduled_minutes_per_day = (shift_end_utc - shift_start_utc).total_seconds() / 60
        workday_set = {d.strip() for d in (company.workdays or "").split(",") if d.strip()}

        approved_leaves = (await self.db.execute(
            select(LeaveRequest).where(
                LeaveRequest.user_id == user.id, LeaveRequest.status == "approved",
                LeaveRequest.start_date <= period_end, LeaveRequest.end_date >= period_start,
            )
        )).scalars().all()
        leave_dates: set[date] = set()
        for lr in approved_leaves:
            d = max(lr.start_date, period_start)
            end = min(lr.end_date, period_end)
            while d <= end:
                leave_dates.add(d)
                d += timedelta(days=1)

        workday_count = 0
        d = period_start
        while d <= period_end:
            if WEEKDAY_CODES[d.weekday()] in workday_set and d not in leave_dates:
                workday_count += 1
            d += timedelta(days=1)

        return round((workday_count * scheduled_minutes_per_day) / 60, 2)

    async def generate_for_user(self, user: User, company: Company, period_start: date, period_end: date) -> Invoice | None:
        """Returns None (skips) if the user has no hourly_fee set -- can't
        produce a meaningful invoice without a rate, and this is expected
        for companies still rolling out invoicing to some employees."""
        if user.hourly_fee is None:
            return None

        exists = (await self.db.execute(select(Invoice).where(
            Invoice.user_id == user.id, Invoice.period_start == period_start, Invoice.period_end == period_end,
        ))).scalar_one_or_none()
        if exists:
            return exists

        if user.actual_working_hours:
            total_hours = await self._actual_hours_for_period(user, period_start, period_end)
        else:
            total_hours = await self._scheduled_hours_for_period(company, user, period_start, period_end)

        total_amount = round(total_hours * float(user.hourly_fee), 2)

        invoice = Invoice(
            company_id=company.id, user_id=user.id,
            period_start=period_start, period_end=period_end,
            hourly_fee=float(user.hourly_fee), total_hours=total_hours, total_amount=total_amount,
            actual_working_hours=user.actual_working_hours,
        )
        self.db.add(invoice)
        await self.db.flush()
        return invoice

    # -------- reading --------
    async def list_for_dashboard(self, employee_id: int | None = None) -> list[Invoice]:
        stmt = self.tenant_select(Invoice).order_by(Invoice.period_start.desc())
        if employee_id is not None:
            target = await self.assert_user_in_tenant(employee_id)
            if not self.can_view_employee(target):
                raise HTTPException(status_code=403, detail="Not allowed for this employee")
            stmt = stmt.where(Invoice.user_id == employee_id)
        return list((await self.db.execute(stmt)).scalars())

    async def my_invoices(self) -> list[Invoice]:
        res = await self.db.execute(
            select(Invoice).where(Invoice.user_id == self.current_user.id).order_by(Invoice.period_start.desc())
        )
        return list(res.scalars())

    async def get_one(self, invoice_id: int) -> Invoice:
        invoice = await self.db.get(Invoice, invoice_id)
        if invoice is None or invoice.company_id != self.company_id:
            raise HTTPException(status_code=404, detail="Invoice not found")
        if invoice.user_id != self.current_user.id:
            owner = await self.assert_user_in_tenant(invoice.user_id)
            if not self.can_view_employee(owner):
                raise HTTPException(status_code=403, detail="Not allowed for this employee")
        return invoice