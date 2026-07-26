"""Invoice generation -- manually triggered only (Owner clicks "Produce
invoices for all" on the dashboard's Invoice List page), never scheduled.
Runs as a queued Celery task so the button returns immediately instead of
blocking on however long it takes to process every employee.

Written as fully self-contained SYNC code (same pattern as
certificates.py) -- Celery tasks in this codebase use SyncSessionLocal and
plain synchronous SQLAlchemy calls, not the async InvoiceService used by
the dashboard's read-only list/detail endpoints (those run inside FastAPI's
async request context and can safely use await; a Celery task cannot).
This duplicates some calculation logic from app/services/invoices.py by
necessity, not oversight -- matching how certificates.py already handles
this exact same async/sync split in this codebase.
"""
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from math import ceil

from sqlalchemy import select

from app.workers.celery_app import SyncSessionLocal, celery_app

WEEKDAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _safe_day(year: int, month: int, day: int) -> int:
    return min(day, monthrange(year, month)[1])


def compute_last_completed_period(pay_period_start_day: int, today: date) -> tuple[date, date]:
    """Same logic as the async version in app/services/invoices.py --
    kept identical between both by necessity since they can't share code
    across the sync/async boundary."""
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


def _deducted_minutes_in_range(db, user_id: int, start_dt: datetime, end_dt: datetime) -> int:
    from app.modules.hr.models.attendance import PresenceCheckPrompt

    rows = db.execute(select(PresenceCheckPrompt).where(
        PresenceCheckPrompt.user_id == user_id, PresenceCheckPrompt.deducted.is_(True),
        PresenceCheckPrompt.sent_at >= start_dt, PresenceCheckPrompt.sent_at <= end_dt,
    )).scalars().all()
    return sum(p.interval_minutes for p in rows)


def _actual_hours_for_period(db, user, company_id: int, period_start: date, period_end: date) -> float:
    from app.modules.hr.models.attendance import AttendanceSession, BreakSession
    from app.core.models.company import CompanySettings

    period_start_dt = datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc)
    period_end_dt = datetime.combine(period_end, datetime.max.time(), tzinfo=timezone.utc)

    sessions = db.execute(select(AttendanceSession).where(
        AttendanceSession.user_id == user.id, AttendanceSession.check_out_at.is_not(None),
        AttendanceSession.check_in_at >= period_start_dt, AttendanceSession.check_in_at <= period_end_dt,
    )).scalars().all()

    deductions_row = db.execute(select(CompanySettings).where(
        CompanySettings.company_id == company_id, CompanySettings.section == "attendance",
    )).scalar_one_or_none()
    deductions_enabled = bool(
        deductions_row.data_json.get("late_no_response_deduction_enabled", True) if deductions_row else True
    )

    total_minutes = 0.0
    for session in sessions:
        check_in = session.check_in_at if session.check_in_at.tzinfo else session.check_in_at.replace(tzinfo=timezone.utc)
        check_out = session.check_out_at if session.check_out_at.tzinfo else session.check_out_at.replace(tzinfo=timezone.utc)
        elapsed_minutes = (check_out - check_in).total_seconds() / 60

        breaks = db.execute(select(BreakSession).where(
            BreakSession.attendance_session_id == session.id
        )).scalars().all()
        break_minutes = 0
        for br in breaks:
            end = br.end_at or check_out
            seconds = (end - br.start_at).total_seconds()
            break_minutes += max(1, ceil(seconds / 60)) if seconds > 0 else 0

        no_response_minutes = (
            _deducted_minutes_in_range(db, user.id, check_in, check_out) if deductions_enabled else 0
        )
        total_minutes += max(0, elapsed_minutes - break_minutes - no_response_minutes)

    return round(total_minutes / 60, 2)


def _scheduled_hours_for_period(db, user, company, period_start: date, period_end: date) -> float:
    from app.modules.hr.models.attendance import LeaveRequest
    from app.core.worktime import compute_shift_bounds_utc

    employee_tz_name = getattr(user, "timezone", None) or company.timezone
    shift_start_utc, shift_end_utc = compute_shift_bounds_utc(
        company.working_hours_start, company.working_hours_end,
        company.timezone, employee_tz_name, company.working_hours_mode,
    )
    scheduled_minutes_per_day = (shift_end_utc - shift_start_utc).total_seconds() / 60
    workday_set = {d.strip() for d in (company.workdays or "").split(",") if d.strip()}

    approved_leaves = db.execute(select(LeaveRequest).where(
        LeaveRequest.user_id == user.id, LeaveRequest.status == "approved",
        LeaveRequest.start_date <= period_end, LeaveRequest.end_date >= period_start,
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


def _render_invoice_pdf(user, company_name: str, period_start: date, period_end: date,
                        total_hours: float, hourly_fee: float, total_amount: float) -> str:
    import os
    import uuid
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas
    from app.core.config import settings as app_settings

    os.makedirs(os.path.join(app_settings.UPLOAD_DIR, "invoices"), exist_ok=True)
    filename = f"invoices/{uuid.uuid4().hex}.pdf"
    path = os.path.join(app_settings.UPLOAD_DIR, filename)

    c = canvas.Canvas(path, pagesize=letter)
    width, height = letter

    c.setFillColor(colors.HexColor("#1f2937"))
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(width / 2, height - 1.2 * inch, "Invoice")

    c.setFont("Helvetica", 12)
    c.setFillColor(colors.HexColor("#4b5563"))
    c.drawCentredString(width / 2, height - 1.6 * inch, company_name)
    c.drawCentredString(width / 2, height - 1.85 * inch, user.full_name or "Employee")
    c.drawCentredString(width / 2, height - 2.05 * inch, f"Period: {period_start.isoformat()} - {period_end.isoformat()}")

    rows = [
        ("Total hours", f"{total_hours:.2f} h"),
        ("Hourly rate", f"{hourly_fee:.2f}"),
        ("Total amount", f"{total_amount:.2f}"),
    ]
    y = height - 2.8 * inch
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(colors.HexColor("#111827"))
    for label, value in rows:
        c.drawString(1.3 * inch, y, label)
        c.drawRightString(width - 1.3 * inch, y, value)
        y -= 0.35 * inch

    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(colors.HexColor("#9ca3af"))
    c.drawCentredString(width / 2, 1 * inch, f"Generated on {date.today().isoformat()}")
    c.showPage()
    c.save()

    return path


@celery_app.task(name="app.modules.hr.workers.tasks.invoices.generate_invoices_for_company")
def generate_invoices_for_company(company_id: int) -> dict:
    from app.core.models.company import Company, CompanySettings
    from app.modules.hr.models.misc import Invoice
    from app.core.models.user import User

    with SyncSessionLocal() as db:
        company = db.get(Company, company_id)
        if company is None:
            return {"generated": 0, "skipped": 0, "error": "Company not found"}

        settings_row = db.execute(select(CompanySettings).where(
            CompanySettings.company_id == company_id, CompanySettings.section == "invoicing",
        )).scalar_one_or_none()
        settings_data = settings_row.data_json if settings_row else {}

        if not settings_data.get("invoice_enabled", False):
            return {"generated": 0, "skipped": 0, "error": "Invoicing is not enabled for this company"}

        pay_period_start_day = int(settings_data.get("pay_period_start_day", 1))
        period_start, period_end = compute_last_completed_period(pay_period_start_day, date.today())

        users = db.execute(select(User).where(
            User.company_id == company_id, User.active.is_(True),
        )).scalars().all()

        generated = 0
        skipped = 0
        for user in users:
            if user.hourly_fee is None:
                skipped += 1
                continue

            already_exists = db.execute(select(Invoice).where(
                Invoice.user_id == user.id, Invoice.period_start == period_start, Invoice.period_end == period_end,
            )).scalar_one_or_none()
            if already_exists:
                skipped += 1
                continue

            if user.actual_working_hours:
                total_hours = _actual_hours_for_period(db, user, company_id, period_start, period_end)
            else:
                total_hours = _scheduled_hours_for_period(db, user, company, period_start, period_end)

            total_amount = round(total_hours * float(user.hourly_fee), 2)
            pdf_url = _render_invoice_pdf(
                user, company.name, period_start, period_end, total_hours, float(user.hourly_fee), total_amount,
            )

            db.add(Invoice(
                company_id=company_id, user_id=user.id,
                period_start=period_start, period_end=period_end,
                hourly_fee=float(user.hourly_fee), total_hours=total_hours, total_amount=total_amount,
                actual_working_hours=user.actual_working_hours, pdf_url=pdf_url,
            ))
            generated += 1

        db.commit()

    return {"generated": generated, "skipped": skipped,
            "period_start": str(period_start), "period_end": str(period_end)}