from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import (DB, ROLE_MANAGER, ROLE_OWNER, CurrentUser,
                                   require_role, RequireActivePlan)
from app.modules.hr.schemas.reports import ProjectAssignmentOut, ProjectIn, ProjectOut, ProjectUpdate
from app.core.services.base import TenantService
from app.modules.hr.services.reports import ReportService

DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))
Owner = Depends(require_role([ROLE_OWNER]))

work_threads_router = APIRouter(prefix="/work-threads", tags=["work-threads"],
                                dependencies=[RequireActivePlan])

@work_threads_router.get("")
async def list_work_threads(db: DB, employee_id: int | None = None,
                            project_id: int | None = None, user=DashUser):
    from datetime import date
    from app.modules.hr.models.reports import WorkThread
    svc = TenantService(db, user)
    stmt = svc.tenant_select_via_user(WorkThread).order_by(WorkThread.last_seen_date.desc()).limit(200)
    if employee_id:
        target = await svc.assert_user_in_tenant(employee_id)
        if not svc.can_view_employee(target):
            raise HTTPException(status_code=403, detail="Not allowed for this employee")
        stmt = stmt.where(WorkThread.user_id == employee_id)
    if project_id:
        stmt = stmt.where(WorkThread.project_id == project_id)
    rows = (await db.execute(stmt)).scalars()
    today = date.today()
    # Frontend's WorkThread type expects `opened_on` and `days_open` -- the
    # model only stores first_seen_date/last_seen_date, and days_open was
    # never computed at all, so both fields came back as undefined
    # (showing as literal "open since day undefined" in the dashboard).
    return [{"id": t.id, "user_id": t.user_id, "project_id": t.project_id, "title": t.title,
             "opened_on": str(t.first_seen_date), "last_seen_date": str(t.last_seen_date),
             "days_open": (today - t.first_seen_date).days, "status": t.status} for t in rows]


projects_router = APIRouter(tags=["projects"])


@projects_router.get("/projects", response_model=list[ProjectOut])
async def list_projects(user: CurrentUser, db: DB, include_inactive: bool = False):
    return await ReportService(db, user).list_projects(include_inactive)


@projects_router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(data: ProjectIn, db: DB, user=DashUser):
    from app.modules.hr.models.reports import Project, ProjectAssignment
    project = Project(
        company_id=user.company_id, name=data.name, description=data.description,
        deal_price=data.deal_price, estimated_start_date=data.estimated_start_date,
        estimated_end_date=data.estimated_end_date,
    )
    db.add(project)
    await db.flush()

    if data.employee_ids:
        for employee_id in set(data.employee_ids):
            db.add(ProjectAssignment(project_id=project.id, user_id=employee_id))
        await db.flush()

    return project


@projects_router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(project_id: int, data: ProjectUpdate, db: DB, user=DashUser):
    from sqlalchemy import delete
    from app.modules.hr.models.reports import Project, ProjectAssignment
    project = await db.get(Project, project_id)
    if project is None or project.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="Project not found")

    payload = data.model_dump(exclude_unset=True)
    # employee_ids isn't a Project column -- handled separately below,
    # replacing the full assignment set rather than merging into it.
    employee_ids = payload.pop("employee_ids", None)
    for field, value in payload.items():
        setattr(project, field, value)

    if employee_ids is not None:
        await db.execute(delete(ProjectAssignment).where(ProjectAssignment.project_id == project_id))
        for employee_id in set(employee_ids):
            db.add(ProjectAssignment(project_id=project_id, user_id=employee_id))

    await db.flush()
    return project


@projects_router.get("/projects/{project_id}/assignments", response_model=list[ProjectAssignmentOut])
async def list_project_assignments(project_id: int, db: DB, user=DashUser):
    from sqlalchemy import select
    from app.modules.hr.models.reports import Project, ProjectAssignment
    from app.core.models.user import User
    project = await db.get(Project, project_id)
    if project is None or project.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = (await db.execute(
        select(User.id, User.full_name, User.email)
        .join(ProjectAssignment, ProjectAssignment.user_id == User.id)
        .where(ProjectAssignment.project_id == project_id)
    )).all()
    return [{"user_id": r.id, "full_name": r.full_name, "email": r.email} for r in rows]


@projects_router.get("/projects/{project_id}/financials")
async def project_financials(project_id: int, db: DB, user=DashUser):
    """Labor cost per employee is computed from Report.hours grouped by
    user, filtered to this project -- NOT from invoicing's actual/scheduled
    toggle or pay-period cutoffs. Reports already require picking a
    project at submission time, making them the natural, existing source
    of "how many hours did this person spend on this project" -- no need
    to reference anything invoicing-related for this purpose. Employees
    with no hourly_fee set are still listed (so it's visible they were
    involved) but contribute 0 to the cost total, with a flag noting no
    rate is set, rather than being silently skipped."""
    from sqlalchemy import func, select
    from app.modules.hr.models.reports import Project, ProjectExpense, Report
    from app.core.models.user import User

    project = await db.get(Project, project_id)
    if project is None or project.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="Project not found")

    hours_rows = (await db.execute(
        select(Report.user_id, func.coalesce(func.sum(Report.hours), 0))
        .where(Report.project_id == project_id)
        .group_by(Report.user_id)
    )).all()

    user_ids = [row[0] for row in hours_rows]
    users_by_id = {}
    if user_ids:
        users_by_id = {
            u.id: u for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars()
        }

    employee_costs = []
    total_labor_cost = 0.0
    for uid, hours in hours_rows:
        person = users_by_id.get(uid)
        hourly_fee = float(person.hourly_fee) if person and person.hourly_fee is not None else None
        cost = round(float(hours) * hourly_fee, 2) if hourly_fee is not None else 0.0
        total_labor_cost += cost
        employee_costs.append({
            "user_id": uid, "name": person.full_name if person else None,
            "hours": float(hours), "hourly_fee": hourly_fee,
            "cost": cost, "rate_missing": hourly_fee is None,
        })

    expenses = list((await db.execute(
        select(ProjectExpense).where(ProjectExpense.project_id == project_id).order_by(ProjectExpense.created_at.desc())
    )).scalars())
    total_custom_expenses = sum(e.amount for e in expenses)

    total_expenses = round(total_labor_cost + total_custom_expenses, 2)
    profit = round(project.deal_price - total_expenses, 2) if project.deal_price is not None else None
    profit_margin_pct = (
        round(profit / project.deal_price * 100, 1) if profit is not None and project.deal_price else None
    )

    return {
        "project_id": project.id, "deal_price": project.deal_price,
        "estimated_start_date": project.estimated_start_date, "estimated_end_date": project.estimated_end_date,
        "completed_at": project.completed_at,
        "employee_costs": employee_costs,
        "custom_expenses": [{"id": e.id, "description": e.description, "amount": e.amount,
                             "created_at": e.created_at} for e in expenses],
        "total_labor_cost": round(total_labor_cost, 2),
        "total_custom_expenses": round(total_custom_expenses, 2),
        "total_expenses": total_expenses,
        "profit": profit,
        "profit_margin_pct": profit_margin_pct,
    }


@projects_router.post("/projects/{project_id}/expenses", status_code=201)
async def add_project_expense(project_id: int, payload: dict, db: DB, user=DashUser):
    from app.modules.hr.models.reports import Project, ProjectExpense
    project = await db.get(Project, project_id)
    if project is None or project.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="Project not found")

    description = (payload.get("description") or "").strip()
    amount = payload.get("amount")
    if not description:
        raise HTTPException(status_code=400, detail="description is required")
    if not isinstance(amount, (int, float)) or amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be a positive number")

    expense = ProjectExpense(project_id=project_id, description=description, amount=float(amount), added_by=user.id)
    db.add(expense)
    await db.flush()
    return {"id": expense.id, "description": expense.description, "amount": expense.amount}


@projects_router.delete("/projects/{project_id}/expenses/{expense_id}", status_code=204)
async def delete_project_expense(project_id: int, expense_id: int, db: DB, user=DashUser):
    from app.modules.hr.models.reports import Project, ProjectExpense
    project = await db.get(Project, project_id)
    if project is None or project.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="Project not found")
    expense = await db.get(ProjectExpense, expense_id)
    if expense is None or expense.project_id != project_id:
        raise HTTPException(status_code=404, detail="Expense not found")
    await db.delete(expense)
    return None