"""Presence-check deduction sweep -- ONLY handles marking overdue,
unanswered prompts as deducted. Sending new presence-check prompts is now
entirely MANUAL, triggered by an Owner/Manager clicking "Send presence
check" on the dashboard for any specific employee they suspect needs one --
whether that employee is marked "working outside today" or just checked in
normally but has been away from the desk area for a long time (see
Location History's geofence indicator).

This sweep still needs to run automatically on a timer regardless of how a
prompt was created, since the whole point is catching prompts nobody
answered within the response window.

Uses a plain SYNC session (SyncSessionLocal), NOT asyncio.run() + an async
session -- that pattern is what caused today's earlier "too many clients
already" connection-leak bug across the other periodic tasks (asyncio.run()
spins up a fresh event loop every call, which doesn't cleanly share the
async engine's connection pool across runs). Sync avoids that whole class
of problem, same as certificates.py already does correctly.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.workers.celery_app import SyncSessionLocal, celery_app

PRESENCE_CHECK_RESPONSE_WINDOW = timedelta(minutes=10)


@celery_app.task(name="attendance.presence_check_deduction_sweep")
def presence_check_deduction_sweep() -> None:
    from app.modules.hr.models.attendance import PresenceCheckPrompt

    response_cutoff = datetime.now(timezone.utc) - PRESENCE_CHECK_RESPONSE_WINDOW

    with SyncSessionLocal() as db:
        overdue = db.execute(
            select(PresenceCheckPrompt).where(
                PresenceCheckPrompt.responded_at.is_(None),
                PresenceCheckPrompt.deducted.is_(False),
                # A manager's revert decision is final -- once reverted,
                # this sweep must never re-deduct it again. Missing this
                # check meant a revert only lasted until the NEXT sweep
                # run (every 5 min), which silently re-deducted the same
                # still-unanswered, still-old prompt right back, wiping
                # out the manager's decision without any indication.
                PresenceCheckPrompt.reverted_at.is_(None),
                PresenceCheckPrompt.sent_at <= response_cutoff,
            )
        ).scalars().all()
        for prompt in overdue:
            prompt.deducted = True
        db.commit()