"""Runs AI workload/pace analysis after a report is submitted (rule 3 compliant)."""
from app.workers.celery_app import SyncSessionLocal, celery_app


@celery_app.task(name="app.workers.tasks.ai_workload.analyze_report", max_retries=3, default_retry_delay=30)
def analyze_report(report_id: int) -> None:
    from app.services.ai_workload import analyze_report_sync

    with SyncSessionLocal() as db:
        analyze_report_sync(db, report_id)
