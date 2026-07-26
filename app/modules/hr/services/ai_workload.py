"""AI workload/pace analysis on a submitted report (rule 3 compliant).

Flow: deterministic SQL computes the employee's recent-hours context ->
openai_client.narrate-style call labels pace from precomputed numbers + the
report summary text. Numbers are never produced by the model.
Runs inside the Celery task workers/tasks/ai_workload.py.
"""
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations import openai_client
from app.modules.hr.models.attendance import AttendanceSession
from app.modules.hr.models.misc import AIWorkloadAnalysis
from app.modules.hr.models.reports import Report


def analyze_report_sync(db: Session, report_id: int) -> AIWorkloadAnalysis | None:
    """Sync variant used by Celery (celery worker uses a sync SQLAlchemy session)."""
    report = db.get(Report, report_id)
    if report is None:
        return None
    existing = db.execute(
        select(AIWorkloadAnalysis).where(AIWorkloadAnalysis.report_id == report_id)
    ).scalar_one_or_none()
    if existing:
        return existing

    # Deterministic context: avg daily hours over the trailing 14 days.
    since = date.today() - timedelta(days=14)
    avg_hours = db.execute(
        select(func.coalesce(func.avg(Report.hours), 0))
        .where(Report.user_id == report.user_id, Report.report_date >= since)
    ).scalar() or 0

    # New: pull that day's attendance session (if any) so the AI's
    # reasoning can reference lateness/early-checkout when relevant --
    # this data existed on AttendanceSession already but was never
    # actually surfaced to the pace analysis at all.
    session_for_day = db.execute(
        select(AttendanceSession)
        .where(
            AttendanceSession.user_id == report.user_id,
            func.date(AttendanceSession.check_in_at) == report.report_date,
        )
        .order_by(AttendanceSession.check_in_at.desc())
    ).scalars().first()

    precomputed = {
        "todays_hours": float(report.hours),
        "avg_daily_hours_14d": round(float(avg_hours), 2),
        "summary_text": report.summary[:2000],
        "late_minutes": session_for_day.late_minutes if session_for_day else None,
        "early_checkout_minutes": session_for_day.early_checkout_minutes if session_for_day else None,
    }
    result = openai_client.label_pace(precomputed)  # returns {"pace_label", "reasoning"}

    analysis = AIWorkloadAnalysis(
        report_id=report.id,
        hours=report.hours,
        ai_pace_label=result["pace_label"],
        ai_reasoning_text=result["reasoning"],
        model_version=settings.OPENAI_TEXT_MODEL,
    )
    db.add(analysis)
    db.commit()
    return analysis