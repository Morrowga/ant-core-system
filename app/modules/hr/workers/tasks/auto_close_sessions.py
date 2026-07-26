"""Auto-checkout safeguard: closes any attendance session that's been open
too long without a real check-out.

This is the actual fix for a real bug class: previously nothing ever forced
a session closed except an explicit check-out call. A forgotten check-out
(or test data left open) would silently persist FOREVER -- the employee
would show as permanently "checked in" from a stale, days-old session, and
every "today" stat (break minutes, late minutes, actual working hours)
would keep computing against that old session indefinitely, since none of
that logic filters by calendar date at all -- it all just reads whatever
session is currently open.

MAX_SESSION_HOURS is deliberately generous (16h) -- long enough that it
never interferes with a real, unusually long workday or approved overtime
bleeding into the next calendar day, but short enough that a session can
never persist for days on end unnoticed.

Register in Celery Beat to run once every hour or so.
"""
from datetime import datetime, timedelta, timezone

from app.workers.celery_app import celery_app

MAX_SESSION_HOURS = 16


@celery_app.task(name="attendance.auto_close_stale_sessions")
def auto_close_stale_sessions() -> int:
    import asyncio
    return asyncio.run(_auto_close_stale_sessions())


async def _auto_close_stale_sessions() -> int:
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.modules.hr.models.attendance import AttendanceSession, BreakSession

    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_SESSION_HOURS)
    closed = 0

    async with AsyncSessionLocal() as db:
        stale = (await db.execute(
            select(AttendanceSession).where(
                AttendanceSession.check_out_at.is_(None),
                AttendanceSession.check_in_at <= cutoff,
            )
        )).scalars().all()

        for session in stale:
            check_in = session.check_in_at if session.check_in_at.tzinfo else session.check_in_at.replace(tzinfo=timezone.utc)
            # Auto-close exactly MAX_SESSION_HOURS after check-in, not "now"
            # -- keeps the recorded duration meaningful/consistent rather
            # than however long this sweep happened to be delayed by.
            session.check_out_at = check_in + timedelta(hours=MAX_SESSION_HOURS)

            # Also close any break still dangling open on this session, same
            # reasoning as the normal check_out() flow already does.
            open_break = (await db.execute(
                select(BreakSession).where(
                    BreakSession.attendance_session_id == session.id, BreakSession.end_at.is_(None),
                )
            )).scalar_one_or_none()
            if open_break is not None:
                open_break.end_at = session.check_out_at

            closed += 1

        await db.commit()
    return closed