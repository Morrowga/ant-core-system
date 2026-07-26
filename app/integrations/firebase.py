"""Firebase Admin wrapper. Only app/services/notifications.py should import this."""
import logging
import os

from app.core.config import settings

logger = logging.getLogger(__name__)
_app = None


def _init():
    global _app
    if _app is not None:
        return _app
    try:
        import firebase_admin
        from firebase_admin import credentials

        if os.path.exists(settings.FIREBASE_CREDENTIALS_PATH):
            cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
            _app = firebase_admin.initialize_app(cred)
        else:
            logger.warning("Firebase credentials not found at %s — pushes are no-ops",
                           settings.FIREBASE_CREDENTIALS_PATH)
    except Exception as exc:  # never let push infra break request handling
        logger.exception("Firebase init failed: %s", exc)
    return _app


def send_push(token: str, title: str, body: str, data: dict | None = None) -> None:
    if _init() is None:
        logger.info("[push:noop] %s -> %s / %s", token[:12], title, body)
        return
    try:
        from firebase_admin import messaging

        messaging.send(messaging.Message(
            token=token,
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
        ))
    except Exception as exc:
        logger.warning("FCM send failed for token %s…: %s", token[:12], exc)
