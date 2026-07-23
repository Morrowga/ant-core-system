"""Shift start/end reminders — sent ~15 minutes before an employee's
scheduled shift start (everyone) and shift end (only those currently
checked in). Uses the same compute_shift_bounds_utc() logic as
shift_status()/check_in(), so this respects per-employee timezone and the
company's working_hours_mode exactly the same way everything else does.

Dedup: checks the existing Notification table for one already sent today
carrying the same extra_data "type" (e.g. "shift_start_reminder") -- this
used to check TITLE TEXT instead, which broke the moment notification text
became localized per-recipient (two people with different languages would
never match on title, defeating the dedup check silently). Matching on the
structured type tag is also just more correct in general, language aside.

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
        users = (await db.execute(
            select(User).where(User.active.is_(True), User.role != "owner_admin")
        )).scalars().all()
        users = [u for u in users if getattr(u, "job_type", "full_time") != "part_time"]

        companies: dict[int, Company] = {}

        for user in users:
            if user.company_id not in companies:
                companies[user.company_id] = await db.get(Company, user.company_id)
            company = companies[user.company_id]

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
                already_sent = await _already_sent_today(db, user.id, "shift_start_reminder")
                if not already_sent:
                    local_start = shift_start_utc.astimezone(ZoneInfo(employee_tz_name)).strftime("%H:%M")
                    await notification_service.send(
                        db, user.id, category="attendance",
                        title_key="attendance.shiftStartReminder.title",
                        body_key="attendance.shiftStartReminder.body",
                        body_params={"time": local_start},
                        extra_data={"type": "shift_start_reminder"},
                    )

            # ---------- shift-end reminder (only if currently checked in) ----------
            if open_session is not None and shift_end_utc - lead <= now < shift_end_utc:
                already_sent = await _already_sent_today(db, user.id, "shift_end_reminder")
                if not already_sent:
                    await notification_service.send(
                        db, user.id, category="attendance",
                        title_key="attendance.shiftEndReminder.title",
                        body_key="attendance.shiftEndReminder.body",
                        extra_data={"type": "shift_end_reminder"},
                    )

        await db.commit()


async def _already_sent_today(db, user_id: int, extra_type: str) -> bool:
    """Matches on extra_data_json["type"], not title text -- title is now
    resolved per-recipient language and would never reliably match across
    calls, and matching on the structured type tag is more correct
    regardless. Fetches today's notifications for this one user and
    filters in Python rather than doing JSON-path filtering in SQL, since
    it's a small, per-user set and keeps this portable across DB backends."""
    from sqlalchemy import select
    from app.models.users import Notification

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (await db.execute(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.created_at >= today_start,
        )
    )).scalars().all()
    return any((row.extra_data_json or {}).get("type") == extra_type for row in rows)