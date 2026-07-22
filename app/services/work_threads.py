"""Work-thread continuity matching (rule 3): embeddings + cosine similarity via
pgvector — the LLM is never called per-comparison.

Runs in Celery task workers/tasks/work_thread_matching.py after a report is saved.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations import openai_client
from app.models.reports import Report, ReportEmbedding, WorkThread, WorkThreadEntry

SIMILARITY_THRESHOLD = 0.82  # cosine similarity above which reports join the same thread


def match_report_sync(db: Session, report_id: int) -> None:
    report = db.get(Report, report_id)
    if report is None or not report.summary:
        return

    # 1. Embed the new report summary (single embeddings call — deterministic math after).
    vector = openai_client.embed([report.summary])[0]
    db.merge(ReportEmbedding(report_id=report.id, embedding=vector))
    db.flush()

    # 2. Find the nearest prior report by this user on this project via pgvector
    #    (<=> is cosine distance; similarity = 1 - distance).
    stmt = (
        select(
            ReportEmbedding.report_id,
            (1 - ReportEmbedding.embedding.cosine_distance(vector)).label("similarity"),
        )
        .join(Report, Report.id == ReportEmbedding.report_id)
        .where(
            Report.user_id == report.user_id,
            Report.project_id == report.project_id,
            Report.id != report.id,
        )
        .order_by(ReportEmbedding.embedding.cosine_distance(vector))
        .limit(1)
    )
    nearest = db.execute(stmt).first()

    if nearest and nearest.similarity is not None and nearest.similarity >= SIMILARITY_THRESHOLD:
        # Continue the existing thread of the nearest report.
        entry = db.execute(
            select(WorkThreadEntry).where(WorkThreadEntry.report_id == nearest.report_id)
        ).scalar_one_or_none()
        if entry:
            thread = db.get(WorkThread, entry.thread_id)
            thread.last_seen_date = report.report_date
            db.add(WorkThreadEntry(thread_id=thread.id, report_id=report.id,
                                   similarity_score=float(nearest.similarity)))
            db.commit()
            return

    # Otherwise start a new thread.
    thread = WorkThread(
        user_id=report.user_id, project_id=report.project_id,
        title=report.summary[:120], first_seen_date=report.report_date,
        last_seen_date=report.report_date, status="active",
    )
    db.add(thread)
    db.flush()
    db.add(WorkThreadEntry(thread_id=thread.id, report_id=report.id, similarity_score=None))
    db.commit()
