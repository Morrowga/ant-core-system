"""Certificate auto-issuance (rule 6): beat-scheduled, no approval gate exists.

Content is intentionally narrative and light on raw numbers — this is a
shareable "certificate of achievement," not an HR stats printout. The exact
figures behind it are still fully deterministic (rule 3) and stored in
data_json for auditability; the PDF just doesn't dump them all on the page.
"""
import os
import uuid
from datetime import date, timedelta

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from sqlalchemy import func, select

from app.core.config import settings as app_settings
from app.workers.celery_app import SyncSessionLocal, celery_app

# Tier thresholds — used only to turn numbers into plain-language descriptions
# for the certificate text (the underlying % is still stored in data_json).
def _attendance_tier(pct: float) -> str:
    if pct >= 95: return "excellent"
    if pct >= 85: return "strong"
    if pct >= 70: return "steady"
    return "developing"


def _pace_tier(dist: dict[str, int]) -> str:
    total = sum(dist.values()) or 1
    steady_heavy = dist.get("steady", 0) + dist.get("heavy", 0)
    if steady_heavy / total >= 0.7:
        return "consistently dependable"
    if dist.get("heavy", 0) / total >= 0.4:
        return "high-intensity"
    return "steady"


def _stats(db, user, period_start: date, period_end: date) -> dict:
    from app.models.attendance import AttendanceSession
    from app.models.misc import AIWorkloadAnalysis, Recognition
    from app.models.reports import OvertimeSession, Report

    hours = db.execute(select(func.coalesce(func.sum(Report.hours), 0)).where(
        Report.user_id == user.id, Report.report_date >= period_start,
        Report.report_date <= period_end)).scalar() or 0

    project_count = db.execute(select(func.count(func.distinct(Report.project_id))).where(
        Report.user_id == user.id, Report.report_date >= period_start,
        Report.report_date <= period_end, Report.project_id.is_not(None))).scalar() or 0

    workdays = sum(1 for i in range((period_end - period_start).days + 1)
                   if (period_start + timedelta(days=i)).weekday() < 5)
    present_days = db.execute(select(func.count(func.distinct(func.date(AttendanceSession.check_in_at)))).where(
        AttendanceSession.user_id == user.id,
        AttendanceSession.check_in_at >= period_start,
        AttendanceSession.check_in_at <= period_end)).scalar() or 0
    attendance_pct = round(present_days / workdays * 100, 1) if workdays else 100.0

    pace_rows = db.execute(
        select(AIWorkloadAnalysis.ai_pace_label, func.count())
        .join(Report, Report.id == AIWorkloadAnalysis.report_id)
        .where(Report.user_id == user.id, Report.report_date >= period_start,
               Report.report_date <= period_end)
        .group_by(AIWorkloadAnalysis.ai_pace_label)
    ).all()
    pace_dist = {label: count for label, count in pace_rows}

    recognitions = db.execute(select(func.count(Recognition.id)).where(
        Recognition.employee_id == user.id,
        Recognition.created_at >= period_start, Recognition.created_at <= period_end)).scalar() or 0

    overtime_hours = db.execute(select(func.coalesce(func.sum(OvertimeSession.hours), 0)).where(
        OvertimeSession.user_id == user.id, OvertimeSession.end_at.is_not(None),
        OvertimeSession.start_at >= period_start, OvertimeSession.start_at <= period_end)).scalar() or 0

    return {
        "hours_logged": float(hours), "project_count": project_count,
        "attendance_pct": attendance_pct, "pace_distribution": pace_dist,
        "recognitions": recognitions, "overtime_hours": float(overtime_hours),
    }


def _render_pdf(user, company_name: str, period_label: str, stats: dict) -> str:
    """Draws a short, achievement-style one-pager. Returns the public URL."""
    os.makedirs(os.path.join(app_settings.UPLOAD_DIR, "certificates"), exist_ok=True)
    filename = f"certificates/{uuid.uuid4().hex}.pdf"
    path = os.path.join(app_settings.UPLOAD_DIR, filename)

    attendance_desc = _attendance_tier(stats["attendance_pct"])
    pace_desc = _pace_tier(stats["pace_distribution"])
    project_word = "project" if stats["project_count"] == 1 else "projects"

    narrative = (
        f"In {period_label}, {user.full_name} worked at {company_name}, "
        f"contributing {stats['hours_logged']:.0f} hours across "
        f"{stats['project_count']} {project_word}. Their work showed a "
        f"{pace_desc} pace, backed by {attendance_desc} attendance."
    )
    if stats["recognitions"] > 0:
        kudos_word = "recognition" if stats["recognitions"] == 1 else "recognitions"
        narrative += f" They earned {stats['recognitions']} {kudos_word} from their team this period."
    if stats["overtime_hours"] > 0:
        narrative += f" They also logged {stats['overtime_hours']:.0f} additional overtime hours."

    c = canvas.Canvas(path, pagesize=letter)
    width, height = letter

    c.setFillColor(colors.HexColor("#1f2937"))
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(width / 2, height - 1.4 * inch, "Certificate of Achievement")

    c.setFont("Helvetica", 13)
    c.setFillColor(colors.HexColor("#4b5563"))
    c.drawCentredString(width / 2, height - 1.9 * inch, company_name)

    c.setFont("Helvetica-Bold", 18)
    c.setFillColor(colors.HexColor("#111827"))
    c.drawCentredString(width / 2, height - 2.6 * inch, user.full_name or "Team Member")

    c.setFont("Helvetica", 11)
    c.setFillColor(colors.HexColor("#111827"))
    text_obj = c.beginText(1.2 * inch, height - 3.3 * inch)
    text_obj.setLeading(18)
    words = narrative.split()
    line, max_chars = "", 78
    for w in words:
        if len(line) + len(w) + 1 > max_chars:
            text_obj.textLine(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        text_obj.textLine(line)
    c.drawText(text_obj)

    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(colors.HexColor("#9ca3af"))
    c.drawCentredString(width / 2, 1 * inch,
                        f"Issued automatically on {date.today().isoformat()} — verified work record")
    c.showPage()
    c.save()

    return path


def _companies_with_setting_disabled(db, period_type: str) -> set[int]:
    """Companies that have explicitly turned off auto-issuance for this
    period type -- previously never checked at all, issue_monthly()/
    issue_yearly() ran unconditionally for every active user in every
    company regardless of this setting."""
    from app.models.company import CompanySettings

    key = "auto_issue_monthly" if period_type == "monthly" else "auto_issue_yearly"
    rows = db.execute(select(CompanySettings).where(CompanySettings.section == "certificates")).scalars().all()
    return {row.company_id for row in rows if row.data_json.get(key, True) is False}


def _issue(period_type: str, period_start: date, period_end: date) -> int:
    from app.models.company import Company
    from app.models.misc import Certificate
    from app.models.users import User

    period_label = (period_start.strftime("%B %Y") if period_type == "monthly"
                    else str(period_start.year))

    issued = 0
    with SyncSessionLocal() as db:
        disabled_company_ids = _companies_with_setting_disabled(db, period_type)
        users = db.execute(select(User).where(User.active.is_(True))).scalars().all()
        for user in users:
            if user.company_id in disabled_company_ids:
                continue

            exists = db.execute(select(Certificate).where(
                Certificate.user_id == user.id,
                Certificate.period_type == period_type,
                Certificate.period_start == period_start)).scalar_one_or_none()
            if exists:
                continue

            company = db.get(Company, user.company_id)
            stats = _stats(db, user, period_start, period_end)
            pdf_url = _render_pdf(user, company.name if company else "", period_label, stats)

            db.add(Certificate(
                user_id=user.id, period_type=period_type,
                period_start=period_start, period_end=period_end,
                data_json=stats,       # full deterministic figures, kept for audit/verification
                pdf_url=pdf_url,
            ))
            issued += 1

            # New: email the certificate directly to the employee -- gives
            # them a permanent copy in their own inbox, independent of
            # whether they can still log into the app later (solves what
            # "departed employee access" was actually trying to achieve,
            # without needing any special post-departure login mechanism).
            if user.email:
                try:
                    from app.integrations.email import send_email
                    send_email(
                        to=user.email,
                        subject=f"Your {period_label} certificate of achievement",
                        body=(
                            f"Hi {user.full_name or 'there'},\n\n"
                            f"Your {period_type} certificate of achievement for {period_label} is attached. "
                            f"You can also view it anytime in the app while your account is active.\n\n"
                            f"— {company.name if company else 'Your company'}"
                        ),
                        attachment_path=pdf_url,
                        attachment_filename=f"certificate_{period_type}_{period_start}.pdf",
                    )
                except Exception:
                    pass  # email delivery hiccup shouldn't block certificate issuance itself
        db.commit()
    return issued


@celery_app.task(name="app.workers.tasks.certificates.issue_monthly")
def issue_monthly() -> int:
    today = date.today()
    period_end = today.replace(day=1) - timedelta(days=1)   # last day of previous month
    period_start = period_end.replace(day=1)
    return _issue("monthly", period_start, period_end)


@celery_app.task(name="app.workers.tasks.certificates.issue_yearly")
def issue_yearly() -> int:
    year = date.today().year - 1
    return _issue("yearly", date(year, 1, 1), date(year, 12, 31))