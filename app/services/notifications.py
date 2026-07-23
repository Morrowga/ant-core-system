"""Single entry point for all pushes (rule 7). Never call FCM directly elsewhere.

Routing: check Redis presence — if the user is active on web, send to web tokens;
else if active on mobile, send to mobile; else default to mobile tokens.
Also persists an in-app Notification row.

New: title/body are no longer passed as literal strings by callers.
Instead, callers pass a translation KEY (+ optional params for
interpolation), and this function resolves the actual text using the
RECIPIENT's own User.language -- so two people in the same company, with
different assigned languages, each get the notification in their own
language. The resolved (already-translated) text is what gets persisted
in the Notification row, not the key -- so historical notifications don't
retroactively change if someone's language is changed later, and no
client (dashboard/portal/mobile) needs any translation logic of its own
to display a notification list; it just shows whatever's in the DB.
"""
import json

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.notification_i18n import translate
from app.integrations import firebase
from app.models.users import DeviceToken, Notification, NotificationPreference

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


PRESENCE_KEY = "presence:{user_id}:{platform}"

# Categories that can NEVER be muted (attendance/payroll-adjacent — hardcoded by
# design, not a company setting): missing these has real money/compliance impact.
NON_MUTABLE_CATEGORIES = ("attendance", "overtime", "payroll", "leave", "alert")


async def muted_categories(db: AsyncSession, user_id: int) -> list[str]:
    row = (await db.execute(select(NotificationPreference).where(
        NotificationPreference.user_id == user_id))).scalar_one_or_none()
    return list(row.muted_categories) if row else []


async def _company_wide_disabled(db: AsyncSession, company_id: int, category: str) -> bool:
    """New: checks the Owner's "Notification categories" company-wide
    toggle (Settings -> Notifications) -- previously this Settings UI
    section had no corresponding check anywhere at all, so disabling a
    category company-wide had zero effect on whether it actually got sent.
    Same exemption as per-user mutes: critical categories can never be
    disabled this way either."""
    if category in NON_MUTABLE_CATEGORIES:
        return False
    from app.models.company import CompanySettings
    row = (await db.execute(select(CompanySettings).where(
        CompanySettings.company_id == company_id, CompanySettings.section == "notifications",
    ))).scalar_one_or_none()
    if row is None:
        return False
    for cat in row.data_json.get("categories", []):
        if cat.get("type") == category:
            return not cat.get("enabled_company_wide", True)
    return False


async def record_heartbeat(user_id: int, platform: str, app_state: str) -> None:
    r = get_redis()
    await r.set(
        PRESENCE_KEY.format(user_id=user_id, platform=platform),
        json.dumps({"app_state": app_state}),
        ex=settings.PRESENCE_TTL_SECONDS,
    )


async def _active_platform(user_id: int) -> str | None:
    r = get_redis()
    if await r.exists(PRESENCE_KEY.format(user_id=user_id, platform="web")):
        return "web"
    if await r.exists(PRESENCE_KEY.format(user_id=user_id, platform="mobile")):
        return "mobile"
    return None


async def send(
    db: AsyncSession,
    user_id: int,
    category: str,
    title_key: str,
    body_key: str = "",
    title_params: dict | None = None,
    body_params: dict | None = None,
    extra_data: dict | None = None,
    audience: str = "employee",
) -> None:
    """The one and only way to notify a user.

    `title_key`/`body_key` are translation keys (see
    app/core/notification_i18n.py), resolved against the RECIPIENT's own
    User.language -- never the sender's/caller's language. `title_params`/
    `body_params` fill in `{{placeholders}}` inside the resolved text
    (e.g. {"time": "09:00"} for "Your shift starts at {{time}}").

    `extra_data` is merged into the FCM push's data payload alongside
    `category` -- lets a caller tag a more specific `type` (e.g.
    "sleep_checkin" vs "mood_water_checkin") so the client can deep-link to
    the exact right screen instead of just knowing the broad category.

    `audience` controls WHICH registered device this can ever reach.
    "dashboard" (Owner/Manager-facing items like desk-location/overtime
    requests) routes ONLY to platform="dashboard" tokens -- never falling
    back to that same person's mobile or portal-web tokens, even if
    that's all they have registered. "employee" (the default) keeps the
    existing mobile/web presence-based routing.
    """
    from app.models.users import User

    # 0a. Respect the company-wide category toggle (Settings -> Notifications).
    user_row = await db.get(User, user_id)
    if user_row is not None and await _company_wide_disabled(db, user_row.company_id, category):
        return
    # 0b. Respect per-user mutes — but critical categories can never be muted.
    if category not in NON_MUTABLE_CATEGORIES and category in await muted_categories(db, user_id):
        return

    # 1. Resolve text in the RECIPIENT's own language, then persist.
    language = getattr(user_row, "language", None) if user_row is not None else None
    title = translate(language, title_key, title_params)
    body = translate(language, body_key, body_params) if body_key else ""

    db.add(Notification(user_id=user_id, category=category, title=title, body=body,
                        extra_data_json=extra_data))
    await db.flush()

    # 2. Route push per presence (rule 7) / audience. Wrapped entirely --
    # any failure here (Firebase not configured, presence lookup issue,
    # etc.) must never affect the in-app Notification row persisted above;
    # that's the one guarantee this function has to keep regardless of
    # push delivery working or not.
    try:
        if audience == "dashboard":
            # Dashboard-bound: ONLY ever the dashboard's own registered
            # tokens. No presence check, no mobile/web fallback -- a
            # Manager's phone should never receive a "someone requested
            # overtime" push meant for the dashboard.
            res = await db.execute(
                select(DeviceToken).where(DeviceToken.user_id == user_id, DeviceToken.platform == "dashboard")
            )
            tokens = [t.fcm_token for t in res.scalars()]
        else:
            platform = await _active_platform(user_id) or "mobile"
            res = await db.execute(
                select(DeviceToken).where(DeviceToken.user_id == user_id, DeviceToken.platform == platform)
            )
            tokens = [t.fcm_token for t in res.scalars()]
            if not tokens and platform == "web":
                # fall back to mobile if the active platform has no registered token
                res = await db.execute(
                    select(DeviceToken).where(DeviceToken.user_id == user_id, DeviceToken.platform == "mobile")
                )
                tokens = [t.fcm_token for t in res.scalars()]

        push_data = {"category": category, **(extra_data or {})}
        for token in tokens:
            try:
                firebase.send_push(token, title, body, data=push_data)
            except Exception:
                pass
    except Exception:
        pass