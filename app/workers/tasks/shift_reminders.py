"""Shift start/end reminders — sent ~15 minutes before an employee's
scheduled shift start (everyone) and shift end (only those currently
checked in). Uses the same compute_shift_bounds_utc() logic as
shift_status()/check_in(), so this respects per-employee timezone and the
company's working_hours_mode exactly the same way everything else does.

Dedup: rather than a new tracking table, this checks the existing
Notification table for one already sent today with a matching category+title
-- reusing infrastructure that's already there. The trigger window is the
full 15 minutes leading up to the moment (not a single instant), so it
fires reliably regardless of small delays in when Beat actually runs this
task, as long as it runs at least once somewhere in that window.

Skips: anyone with a holiday today (their own country, or a company-wide
one) or approved leave covering today -- no reason to remind someone about
a shift they're not expected to work.

Register in Celery Beat to run every ~5 minutes.
"""
from datetime import datetime, timedelta, timezone

from app.workers.celery_app import celery_app

REMINDER_LEAD_MINUTES = 15


@celery_app.task(name="attendance.send_shift_reminders")
def send_shift_reminders() -> None:
    import asyncio
    asyncio.run(_send_shift_reminders())


async def _send_shift_reminders() -> None:
    from sqlalchemy import select
    from zoneinfo import ZoneInfo
    from app.core.worktime import compute_shift_bounds_utc
    from app.db.session import AsyncSessionLocal as SessionLocal
    from app.models.attendance import AttendanceSession, LeaveRequest
    from app.models.company import Company, Holiday
    from app.models.users import User
    from app.services import notifications as notification_service

    now = datetime.now(timezone.utc)
    today = now.date()
    lead = timedelta(minutes=REMINDER_LEAD_MINUTES)

    async with SessionLocal() as db:
        # New: Owner is excluded -- shift reminders are about personal
        # attendance schedules, and the Owner isn't expected to be "on
        # shift" the same way employees/managers are. Previously this had
        # no role filter at all, so Owner got reminded about their own
        # shift like everyone else, which made no sense for that role.
        # Also new: part-time employees have no fixed shift at all (see
        # AttendanceService.check_in()) -- reminding them about a "shift
        # start" that doesn't apply to them makes no sense either.
        users = (await db.execute(
            select(User).where(User.active.is_(True), User.role != "owner_admin")
        )).scalars().all()
        users = [u for u in users if getattr(u, "job_type", "full_time") != "part_time"]

        # Cache one Company row per company_id -- most employees share one.
        companies: dict[int, Company] = {}

        for user in users:
            if user.company_id not in companies:
                companies[user.company_id] = await db.get(Company, user.company_id)
            company = companies[user.company_id]

            # Skip holidays (own country, or company-wide "all").
            if user.holiday_country:
                is_holiday = (await db.execute(
                    select(Holiday).where(
                        Holiday.company_id == user.company_id,
                        Holiday.date == today,
                        (Holiday.country_code == user.holiday_country) | (Holiday.country_code == "all"),
                    ).limit(1)
                )).scalar_one_or_none()
                if is_holiday is not None:
                    continue

            # Skip approved leave covering today.
            on_leave = (await db.execute(
                select(LeaveRequest).where(
                    LeaveRequest.user_id == user.id, LeaveRequest.status == "approved",
                    LeaveRequest.start_date <= today, LeaveRequest.end_date >= today,
                ).limit(1)
            )).scalar_one_or_none()
            if on_leave is not None:
                continue

            employee_tz_name = user.timezone or company.timezone
            shift_start_utc, shift_end_utc = compute_shift_bounds_utc(
                company.working_hours_start, company.working_hours_end,
                company.timezone, employee_tz_name, company.working_hours_mode,
            )

            open_session = (await db.execute(
                select(AttendanceSession).where(
                    AttendanceSession.user_id == user.id, AttendanceSession.check_out_at.is_(None),
                )
            )).scalar_one_or_none()

            # ---------- shift-start reminder (everyone not already checked in) ----------
            if open_session is None and shift_start_utc - lead <= now < shift_start_utc:
                already_sent = await _already_sent_today(db, user.id, "Shift starting soon")
                if not already_sent:
                    local_start = shift_start_utc.astimezone(ZoneInfo(employee_tz_name)).strftime("%H:%M")
                    await notification_service.send(
                        db, user.id, category="attendance",
                        title="Shift starting soon",
                        body=f"Your shift starts at {local_start} — check in when you're ready.",
                        extra_data={"type": "shift_start_reminder"},
                    )

            # ---------- shift-end reminder (only if currently checked in) ----------
            if open_session is not None and shift_end_utc - lead <= now < shift_end_utc:
                already_sent = await _already_sent_today(db, user.id, "Shift ending soon")
                if not already_sent:
                    await notification_service.send(
                        db, user.id, category="attendance",
                        title="Shift ending soon",
                        body="Your shift ends in about 15 minutes — don't forget to check out.",
                        extra_data={"type": "shift_end_reminder"},
                    )

        await db.commit()


async def _already_sent_today(db, user_id: int, title: str) -> bool:
    from sqlalchemy import select
    from app.models.users import Notification

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    existing = (await db.execute(
        select(Notification).where(
            Notification.user_id == user_id, Notification.title == title,
            Notification.created_at >= today_start,
        ).limit(1)
    )).scalar_one_or_none()
    return existing is not None