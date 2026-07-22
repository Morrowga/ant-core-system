from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import DB, ROLE_MANAGER, ROLE_OWNER, CurrentUser, require_role, RequireActivePlan
from app.schemas.reports import (ReportCommentIn, ReportEntryIn, ReportOut, ReportUpdate)
from app.services.reports import ReportService

router = APIRouter(tags=["reports"], dependencies=[RequireActivePlan])
DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))


@router.post("/reports", response_model=list[ReportOut], status_code=201)
async def submit_reports(entries: list[ReportEntryIn], user: CurrentUser, db: DB):
    """Accepts a batch of {project_id, hours, summary}. Each report gets
    editable_until = next local midnight (company tz) and is queued for
    AI workload analysis + work-thread matching (Celery).

    Gated on every health check-in reminder sent TODAY being answered first
    -- if the employee has any unanswered sleep/mood/water prompt from
    today, they must answer it before they can submit their report. Scoped
    to today only so an old missed prompt (e.g. from a day they were on
    leave) doesn't block them indefinitely."""
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.models.misc import HealthCheckinPrompt

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    pending = (await db.execute(
        select(HealthCheckinPrompt).where(
            HealthCheckinPrompt.user_id == user.id,
            HealthCheckinPrompt.responded_at.is_(None),
            HealthCheckinPrompt.sent_at >= today_start,
        )
    )).scalars().all()
    if pending:
        raise HTTPException(
            status_code=409,
            detail=f"Answer your pending health check-in{'s' if len(pending) > 1 else ''} first "
                    f"({len(pending)} unanswered).",
        )

    reports = await ReportService(db, user).create_reports(entries)
    await db.commit()  # commit before enqueueing so workers can see the rows
    try:
        from app.workers.tasks.ai_workload import analyze_report
        from app.workers.tasks.work_thread_matching import match_report
        for r in reports:
            analyze_report.delay(r.id)
            match_report.delay(r.id)
    except Exception:
        pass  # broker down shouldn't fail the submit; a periodic sweep can catch up
    return reports


@router.get("/reports/me", response_model=list[ReportOut])
async def my_reports(user: CurrentUser, db: DB):
    return await ReportService(db, user).my_reports()


@router.patch("/reports/{report_id}", response_model=ReportOut)
async def edit_report(report_id: int, patch: ReportUpdate, user: CurrentUser, db: DB):
    """403 after local midnight — same-day edit window (business rule 4)."""
    return await ReportService(db, user).update_report(report_id, patch)


@router.delete("/reports/{report_id}", status_code=204)
async def delete_report(report_id: int, user: CurrentUser, db: DB):
    await ReportService(db, user).delete_report(report_id)
    return None


@router.post("/reports/no-project-today", status_code=201)
async def no_project_today(user: CurrentUser, db: DB):
    """New: only actually creates the alert if this alert type is enabled
    in the company's AlertSetting -- previously created unconditionally,
    ignoring whatever the Owner configured for this type."""
    from sqlalchemy import select
    from app.models.misc import Alert, AlertSetting

    alert_setting = (await db.execute(
        select(AlertSetting).where(
            AlertSetting.company_id == user.company_id, AlertSetting.type == "no_project_reported",
        )
    )).scalar_one_or_none()
    if alert_setting is None or alert_setting.enabled:
        alert = Alert(company_id=user.company_id, user_id=user.id, type="no_project_reported", status="open")
        db.add(alert)
        await db.flush()
    return {"acknowledged": True}


# ---------- dashboard side ----------
@router.get("/reports", response_model=list[ReportOut])
async def list_reports(db: DB, employee_id: int | None = None, project_id: int | None = None, user=DashUser):
    return await ReportService(db, user).list_reports(employee_id, project_id)


@router.get("/reports/no-project-notifications")
async def no_project_notifications(db: DB, user=DashUser):
    """Company-wide (manager: own team only) feed of no_project_reported
    alerts, raised by POST /reports/no-project-today. Must stay ABOVE
    GET /reports/{report_id} below -- otherwise a request to this literal
    path falls through to the dynamic route, which tries (and fails) to
    parse "no-project-notifications" as an integer report_id."""
    from sqlalchemy import select
    from app.models.misc import Alert
    from app.models.users import User

    stmt = (
        select(Alert.user_id, Alert.created_at, User.full_name)
        .join(User, User.id == Alert.user_id)
        .where(Alert.company_id == user.company_id, Alert.type == "no_project_reported")
        .order_by(Alert.created_at.desc())
        .limit(100)
    )
    if user.role == ROLE_MANAGER:
        stmt = stmt.where(User.team_id == user.team_id)

    rows = (await db.execute(stmt)).all()
    return [
        {"user_id": user_id, "employee_name": full_name, "date": str(created_at.date())}
        for user_id, created_at, full_name in rows
    ]


@router.get("/reports/{report_id}")
async def get_report(report_id: int, db: DB, user: CurrentUser):
    """Was DashUser-only (Owner/Manager) -- rejected employees with a 403
    before even reaching this function, even for their OWN report. Now any
    authenticated user can call this; the report's own author is always
    allowed, and anyone else still goes through the normal tenant +
    can_view_employee checks below."""
    from sqlalchemy import select
    from app.models.misc import AIWorkloadAnalysis
    from app.models.reports import Project, Report, ReportComment
    from app.models.users import User

    svc = ReportService(db, user)
    report = await db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    if report.user_id != user.id:
        owner = await svc.assert_user_in_tenant(report.user_id)
        if not svc.can_view_employee(owner):
            raise HTTPException(status_code=403, detail="Not allowed for this employee")
        owner_name = owner.full_name
    else:
        owner_name = user.full_name

    project = await db.get(Project, report.project_id) if report.project_id else None

    analysis = (await db.execute(
        select(AIWorkloadAnalysis).where(AIWorkloadAnalysis.report_id == report_id)
    )).scalar_one_or_none()

    comment_rows = (await db.execute(
        select(ReportComment, User.full_name)
        .join(User, User.id == ReportComment.author_id)
        .where(ReportComment.report_id == report_id)
        .order_by(ReportComment.created_at)
    )).all()

    return {
        "id": report.id,
        "user_id": report.user_id,
        "employee_name": owner_name,
        "project_id": report.project_id,
        "project_name": project.name if project else None,
        "hours": report.hours,
        "summary": report.summary,
        "report_date": report.report_date,
        "editable_until": report.editable_until,
        "created_at": report.created_at,
        "comments": [
            {"id": c.id, "comment": c.comment, "author_name": author_name, "created_at": c.created_at}
            for c, author_name in comment_rows
        ],
        "ai_analysis": None if analysis is None else {
            "pace_label": analysis.ai_pace_label,
            "reasoning": analysis.ai_reasoning_text,
            "model_version": analysis.model_version,
        },
    }


@router.post("/reports/{report_id}/comment", status_code=201)
async def comment_report(report_id: int, data: ReportCommentIn, db: DB, user=DashUser):
    rc = await ReportService(db, user).comment(report_id, data.comment)
    return {"id": rc.id}