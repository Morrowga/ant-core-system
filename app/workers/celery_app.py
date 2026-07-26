"""Celery app.

Why Celery (vs APScheduler): the spec needs BOTH event-driven jobs (AI workload
analysis and work-thread matching fired on each report submit) and scheduled
jobs (alert escalation sweeps, monthly/yearly certificate issuance). Celery +
Redis covers both (delay() + beat), scales to multiple workers, and Redis is
already in the stack — so it adds no new infrastructure. APScheduler would only
cover the scheduled half cleanly and runs in-process, which doesn't survive
multi-instance API deployments.
"""
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "workforce",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.modules.hr.workers.tasks.alerts",
        "app.modules.hr.workers.tasks.certificates",
        "app.modules.hr.workers.tasks.invoices",
        "app.modules.hr.workers.tasks.ai_workload",
        "app.modules.hr.workers.tasks.work_thread_matching",
        "app.modules.hr.workers.tasks.health_reminders",
        "app.modules.hr.workers.tasks.presence_checks",
        "app.modules.hr.workers.tasks.shift_reminders",
        "app.modules.hr.workers.tasks.auto_close_sessions",
    ],
)

celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    "alert-escalation-sweep": {
        "task": "app.modules.hr.workers.tasks.alerts.escalation_sweep",
        "schedule": 300.0,  # every 5 minutes
    },
    "issue-monthly-certificates": {
        "task": "app.modules.hr.workers.tasks.certificates.issue_monthly",
        "schedule": crontab(day_of_month=1, hour=2, minute=0),
    },
    "issue-yearly-certificates": {
        "task": "app.modules.hr.workers.tasks.certificates.issue_yearly",
        "schedule": crontab(month_of_year=1, day_of_month=1, hour=3, minute=0),
    },
    "send-health-checkin-reminders": {
        "task": "health.send_mood_water_reminders",
        "schedule": 900.0,  # every 15 minutes -- task itself only actually
                             # sends to sessions where 2h+ has passed since
                             # the last prompt, so this cadence just keeps
                             # the check tight, it doesn't spam every 15min
    },
    "presence-check-deduction-sweep": {
        "task": "attendance.presence_check_deduction_sweep",
        "schedule": 300.0,  # every 5 minutes -- catches the 10-min
                             # deduction window without drift. Sending new
                             # prompts is no longer automatic at all --
                             # that's now a manual dashboard action, so
                             # this only ever marks already-sent, overdue,
                             # unanswered prompts as deducted.
    },
    "send-shift-reminders": {
        "task": "attendance.send_shift_reminders",
        "schedule": 300.0,  # every 5 minutes -- fits inside the 15-min
                             # trigger window with room to spare
    },
    "auto-close-stale-sessions": {
        "task": "attendance.auto_close_stale_sessions",
        "schedule": 3600.0,  # every hour -- a forgotten check-out shouldn't
                              # be able to persist for more than ~1h past
                              # the 16h cutoff before getting cleaned up
    },
}


# Sync SQLAlchemy session for workers (Celery tasks are sync).
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sync_engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
SyncSessionLocal = sessionmaker(bind=sync_engine)