"""Alert escalation sweep: escalate open alerts past their configured delay,
and actually notify the roles configured to hear about it.

Fixes two real gaps from the previous version:
- Disabled alert types (AlertSetting.enabled == False) were still being
  escalated with a hardcoded 15-min fallback delay -- disabling a type had
  no effect on escalation at all. Now disabled types are skipped entirely.
- notify_roles was stored but never read anywhere -- escalation only ever
  flipped alert.status, nobody was ever actually notified. Now it looks up
  every matching user and sends them a real notification.

Converted from a sync-session task to the same async pattern used by
health_reminders.py / presence_checks.py, since notification_service.send()
is an async function requiring an AsyncSession -- the previous version's
SyncSessionLocal usage could never have actually called it correctly.
"""
from datetime import datetime, timedelta, timezone

from app.workers.celery_app import celery_app

DEFAULT_ESCALATION_DELAY_MINUTES = 15


@celery_app.task(name="app.workers.tasks.alerts.escalation_sweep")
def escalation_sweep() -> int:
    import asyncio
    return asyncio.run(_escalation_sweep())


async def _escalation_sweep() -> int:
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal as SessionLocal
    from app.models.misc import Alert, AlertSetting
    from app.models.users import User
    from app.services import notifications as notification_service

    escalated = 0
    async with SessionLocal() as db:
        alerts = (await db.execute(select(Alert).where(Alert.status == "open"))).scalars().all()
        settings_cache: dict[tuple[int, str], AlertSetting | None] = {}

        for alert in alerts:
            key = (alert.company_id, alert.type)
            if key not in settings_cache:
                settings_cache[key] = (await db.execute(select(AlertSetting).where(
                    AlertSetting.company_id == alert.company_id,
                    AlertSetting.type == alert.type))).scalar_one_or_none()
            setting = settings_cache[key]

            # Disabled types are skipped entirely -- previously they still
            # escalated with a 15-min fallback regardless of this flag.
            if setting is not None and not setting.enabled:
                continue

            delay = setting.escalation_delay_minutes if setting else DEFAULT_ESCALATION_DELAY_MINUTES
            created = alert.created_at if alert.created_at.tzinfo else alert.created_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created <= timedelta(minutes=delay):
                continue

            alert.status = "escalated"
            alert.escalated_at = datetime.now(timezone.utc)
            escalated += 1

            # New: actually notify whoever notify_roles says should hear
            # about this. Falls back to owner_admin only if nothing is
            # configured, so escalation is never completely silent.
            # Handles both string and list representations, since the
            # Settings UI's role fields have been confirmed to sometimes
            # send an array rather than a comma-separated string.
            raw_notify_roles = setting.notify_roles if setting else None
            if isinstance(raw_notify_roles, list):
                roles = {str(r).strip() for r in raw_notify_roles if str(r).strip()}
            elif raw_notify_roles:
                roles = {r.strip() for r in str(raw_notify_roles).split(",") if r.strip()}
            else:
                roles = {"owner_admin"}

            recipient_stmt = select(User).where(
                User.company_id == alert.company_id, User.role.in_(roles), User.active.is_(True),
            )
            # If this alert is about a specific employee and "manager" is
            # one of the target roles, only that employee's own manager
            # should hear about it, not every manager in the company.
            if alert.user_id is not None and "manager" in roles:
                subject = await db.get(User, alert.user_id)
                if subject is not None and subject.team_id is not None:
                    recipient_stmt = recipient_stmt.where(
                        (User.role != "manager") | (User.team_id == subject.team_id)
                    )

            recipients = (await db.execute(recipient_stmt)).scalars().all()
            for recipient in recipients:
                await notification_service.send(
                    db, recipient.id, category="alert",
                    title="Alert escalated",
                    body=f"An unacknowledged {alert.type.replace('_', ' ')} alert needs attention.",
                    extra_data={"type": "alert_escalated", "alert_id": str(alert.id)},
                )

        await db.commit()
    return escalated