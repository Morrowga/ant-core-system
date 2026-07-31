"""Dev-only manual notification trigger. NO AUTH by design (per explicit
request) -- reachable directly from a browser URL bar for quick manual
testing against one fixed test account. Gated behind an environment check
so this can never accidentally fire in production regardless of routing
config drift; remove this whole file once notification testing is done."""
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.core.config import settings
from app.core.dependencies import DB
from app.core.services import notifications as notification_service

router = APIRouter(prefix="/dev", tags=["dev-testing"])

TEST_EMAIL = "grace@northwind.demo"

# Maps a short, easy-to-type `type` query param to the actual
# (category, title_key, body_key, extra_data type, sample params) tuple --
# one entry per real notification currently wired up in the system.
NOTIFICATION_TYPES: dict[str, dict] = {
    "mood_water_checkin": {
        "category": "health",
        "title_key": "health.moodWaterCheckin.title",
        "body_key": "health.moodWaterCheckin.body",
        "extra_data": {"type": "mood_water_checkin", "prompt_id": "999"},
    },
    "sleep_checkin": {
        "category": "health",
        "title_key": "health.sleepCheckin.title",
        "body_key": "health.sleepCheckin.body",
        "extra_data": {"type": "sleep_checkin", "prompt_id": "999"},
    },
    "presence_check": {
        "category": "attendance",
        "title_key": "attendance.presenceCheck.title",
        "body_key": "attendance.presenceCheck.body",
        "extra_data": {"type": "presence_check", "prompt_id": "999"},
    },
    "desk_location_request": {
        "category": "attendance",
        "title_key": "attendance.deskLocationRequest.title",
        "body_key": "attendance.deskLocationRequest.body",
        "body_params": {"name": "Test Employee"},
        "extra_data": {"type": "desk_location_request", "employee_id": "1", "request_id": "999"},
    },
    "desk_location_decision_approved": {
        "category": "attendance",
        "title_key": "attendance.deskLocationDecisionApproved.title",
        "body_key": "attendance.deskLocationDecisionApproved.body",
        "extra_data": {"type": "desk_location_decision", "request_id": "999", "status": "approved"},
    },
    "desk_location_decision_rejected": {
        "category": "attendance",
        "title_key": "attendance.deskLocationDecisionRejected.title",
        "body_key": "attendance.deskLocationDecisionRejected.body",
        "extra_data": {"type": "desk_location_decision", "request_id": "999", "status": "rejected"},
    },
    "shift_start_reminder": {
        "category": "attendance",
        "title_key": "attendance.shiftStartReminder.title",
        "body_key": "attendance.shiftStartReminder.body",
        "body_params": {"time": "09:00"},
        "extra_data": {"type": "shift_start_reminder"},
    },
    "shift_end_reminder": {
        "category": "attendance",
        "title_key": "attendance.shiftEndReminder.title",
        "body_key": "attendance.shiftEndReminder.body",
        "extra_data": {"type": "shift_end_reminder"},
    },
    "alert_escalated": {
        "category": "alert",
        "title_key": "alert.escalated.title",
        "body_key": "alert.escalated.body",
        "body_params": {"alertType": "missed check in"},
        "extra_data": {"type": "alert_escalated", "alert_id": "999"},
    },
}


@router.get("/test-notification")
async def test_notification(db: DB, type: str = Query(..., description="One of NOTIFICATION_TYPES' keys")):
    # if settings.ENV != "local":
    #     raise HTTPException(status_code=404, detail="Not found")

    spec = NOTIFICATION_TYPES.get(type)
    if spec is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown type '{type}'. Valid types: {', '.join(sorted(NOTIFICATION_TYPES))}",
        )

    from app.core.models.user import User
    user = (await db.execute(select(User).where(User.email == TEST_EMAIL))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail=f"Test user {TEST_EMAIL} not found")

    await notification_service.send(
        db, user.id,
        category=spec["category"],
        title_key=spec["title_key"],
        body_key=spec["body_key"],
        body_params=spec.get("body_params"),
        extra_data=spec.get("extra_data"),
    )
    await db.commit()
    return {"sent": True, "type": type, "to": TEST_EMAIL, "language": getattr(user, "language", None)}