"""Periodic health check-in reminder, every ~2 hours during an active
attendance session. Water and mood are asked together in ONE combined
survey-style form (one notification, one prompt, one submit). Sleep is NOT
part of this cycle at all; it's asked once, at check-in only (see
AttendanceService.check_in()).

New: skips anyone for whom today is a holiday (their assigned
holiday_country, or a company-wide holiday) -- confirmed explicitly that
health reminders should pause on holidays too, same as regular work
expectations.

Register this in your Celery Beat schedule to run frequently (e.g. every
15 minutes) -- the task itself only sends to sessions where 2+ hours have
passed since the last prompt, so running it often just keeps the check
tight, it doesn't spam.
"""
from datetime import datetime, timedelta, timezone

from app.workers.celery_app import celery_app

HEALTH_PROMPT_INTERVAL = timedelta(hours=2)


@celery_app.task(name="health.send_mood_water_reminders")
def send_mood_water_reminders() -> None:
    import asyncio
    asyncio.run(_send_mood_water_reminders())


async def _send_mood_water_reminders() -> None:
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal as SessionLocal
    from app.models.attendance import AttendanceSession
    from app.models.company import Holiday
    from app.models.misc import HealthCheckinPrompt
    from app.models.users import User
    from app.services import notifications as notification_service

    cutoff = datetime.now(timezone.utc) - HEALTH_PROMPT_INTERVAL
    today = datetime.now(timezone.utc).date()

    async with SessionLocal() as db:
        stmt = (
            select(AttendanceSession, User.company_id, User.holiday_country)
            .join(User, User.id == AttendanceSession.user_id)
            .where(
                AttendanceSession.check_out_at.is_(None),  # only currently-active sessions (rule 1)
                (AttendanceSession.last_health_prompt_at.is_(None))
                | (AttendanceSession.last_health_prompt_at <= cutoff),
            )
        )
        rows = (await db.execute(stmt)).all()

        for session, company_id, holiday_country in rows:
            # Skip if today is a holiday for this person -- either their
            # own assigned country, or a company-wide holiday ("all").
            if holiday_country is not None:
                is_holiday = (await db.execute(
                    select(Holiday).where(
                        Holiday.company_id == company_id,
                        Holiday.date == today,
                        (Holiday.country_code == holiday_country) | (Holiday.country_code == "all"),
                    ).limit(1)
                )).scalar_one_or_none()
                if is_holiday is not None:
                    continue

            prompt = HealthCheckinPrompt(company_id=company_id, user_id=session.user_id, type="mood_water_checkin")
            db.add(prompt)
            await db.flush()

            await notification_service.send(
                db, session.user_id, category="health",
                title_key="health.moodWaterCheckin.title",
                body_key="health.moodWaterCheckin.body",
                extra_data={"type": "mood_water_checkin", "prompt_id": str(prompt.id)},
            )
            session.last_health_prompt_at = datetime.now(timezone.utc)

        await db.commit()