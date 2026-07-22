"""Embeds a report summary and links it to a work thread via cosine similarity."""
from app.workers.celery_app import SyncSessionLocal, celery_app


@celery_app.task(name="app.workers.tasks.work_thread_matching.match_report", max_retries=3, default_retry_delay=30)
def match_report(report_id: int) -> None:
    from app.services.work_threads import match_report_sync

    with SyncSessionLocal() as db:
        match_report_sync(db, report_id)
