from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.dependencies import DB, CurrentUser, RequireActivePlan
from app.models.users import DeviceToken, Notification
from app.schemas.misc import DeviceRegisterIn, HeartbeatIn
from app.services import notifications as notification_service

router = APIRouter(tags=["notifications"], dependencies=[RequireActivePlan])


@router.post("/notifications/register-device", status_code=201)
async def register_device(data: DeviceRegisterIn, user: CurrentUser, db: DB):
    existing = (await db.execute(select(DeviceToken).where(DeviceToken.fcm_token == data.fcm_token))).scalar_one_or_none()
    if existing:
        existing.user_id, existing.platform = user.id, data.platform
    else:
        db.add(DeviceToken(user_id=user.id, fcm_token=data.fcm_token, platform=data.platform))
    await db.flush()
    return {"ok": True}


@router.delete("/notifications/device/{token}", status_code=204)
async def unregister_device(token: str, user: CurrentUser, db: DB):
    row = (await db.execute(select(DeviceToken).where(
        DeviceToken.fcm_token == token, DeviceToken.user_id == user.id))).scalar_one_or_none()
    if row:
        await db.delete(row)
    return None


@router.get("/notifications/me")
async def my_notifications(user: CurrentUser, db: DB, admin_view: bool = False):
    """New: `admin_view=true` excludes personal/individual reminder
    notifications (shift start/end, health check-ins, presence checks) --
    those are things a person needs to act on for THEMSELVES, and never
    belong in the dashboard's notification bell/list, which is for
    administrative items (someone else needing a decision) regardless of
    who's logged in. Mobile calls this WITHOUT admin_view and continues to
    see everything, unfiltered."""
    res = await db.execute(select(Notification).where(Notification.user_id == user.id)
                           .order_by(Notification.created_at.desc()).limit(100))
    rows = list(res.scalars())

    if admin_view:
        PERSONAL_REMINDER_TYPES = {
            "shift_start_reminder", "shift_end_reminder",
            "sleep_checkin", "mood_water_checkin", "presence_check",
        }
        rows = [
            n for n in rows
            if not (n.extra_data_json and n.extra_data_json.get("type") in PERSONAL_REMINDER_TYPES)
        ]

    return [{"id": n.id, "category": n.category, "title": n.title, "body": n.body,
             "read_at": n.read_at, "created_at": n.created_at,
             "extra_data": n.extra_data_json} for n in rows]


@router.patch("/notifications/{notification_id}/read")
async def mark_read(notification_id: int, user: CurrentUser, db: DB):
    from datetime import datetime, timezone
    n = await db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.read_at = datetime.now(timezone.utc)
    await db.flush()
    return {"ok": True}


@router.post("/presence/heartbeat", status_code=204)
async def heartbeat(data: HeartbeatIn, user: CurrentUser):
    await notification_service.record_heartbeat(user.id, data.platform, data.app_state)
    return None

@router.get("/notifications/preferences")
async def get_preferences(user: CurrentUser, db: DB):
    from app.models.users import NotificationPreference
    from app.services.notifications import NON_MUTABLE_CATEGORIES
    row = (await db.execute(select(NotificationPreference).where(
        NotificationPreference.user_id == user.id))).scalar_one_or_none()
    return {"muted_categories": list(row.muted_categories) if row else [],
            "non_mutable_categories": list(NON_MUTABLE_CATEGORIES)}


@router.patch("/notifications/preferences")
async def update_preferences(payload: dict, user: CurrentUser, db: DB):
    """Mute/unmute non-critical categories. Attendance/payroll-adjacent categories
    (NON_MUTABLE_CATEGORIES) are rejected — they can never be muted.

    "health" is additionally rejected if the company's health settings have
    employee_can_opt_out_individually set to false -- this was previously
    saved as a company setting but never actually checked anywhere; an
    employee could always mute health regardless of what the Owner set."""
    from app.models.company import CompanySettings
    from app.models.users import NotificationPreference
    from app.services.notifications import NON_MUTABLE_CATEGORIES

    requested = payload.get("muted_categories")
    if not isinstance(requested, list) or not all(isinstance(c, str) for c in requested):
        raise HTTPException(status_code=400, detail="muted_categories must be a list of strings")

    not_mutable = set(NON_MUTABLE_CATEGORIES)

    if "health" in requested:
        health_settings_row = (await db.execute(select(CompanySettings).where(
            CompanySettings.company_id == user.company_id, CompanySettings.section == "health",
        ))).scalar_one_or_none()
        can_opt_out = bool(health_settings_row.data_json.get("employee_can_opt_out_individually", True)) \
            if health_settings_row else True
        if not can_opt_out:
            not_mutable = not_mutable | {"health"}

    blocked = sorted(set(requested) & not_mutable)
    if blocked:
        raise HTTPException(status_code=400,
                            detail=f"These categories cannot be muted: {', '.join(blocked)}")
    row = (await db.execute(select(NotificationPreference).where(
        NotificationPreference.user_id == user.id))).scalar_one_or_none()
    if row is None:
        row = NotificationPreference(user_id=user.id, muted_categories=requested)
        db.add(row)
    else:
        row.muted_categories = requested
    await db.flush()
    return {"muted_categories": requested}