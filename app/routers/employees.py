from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import DB, ROLE_MANAGER, ROLE_OWNER, require_role,RequireActivePlan
from app.models.users import Team, User
from app.schemas.users import (ActualWorkingHoursUpdate, EmployeeAdminUpdate, HolidayCountryUpdate,
                                HourlyFeeUpdate, JobTypeUpdate, LanguageUpdate, RoleUpdate, TeamAssign,
                                TeamCreate, TeamOut, TimezoneUpdate, UserOut)
from app.services.base import TenantService

router = APIRouter(tags=["employees"], dependencies=[RequireActivePlan])
DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))


@router.get("/employees", response_model=list[UserOut])
async def list_employees(db: DB, user=DashUser):
    svc = TenantService(db, user)
    stmt = svc.tenant_select(User)
    if user.role == ROLE_MANAGER:  # managers: team-scoped visibility
        stmt = stmt.where(User.team_id == user.team_id)
    return list((await db.execute(stmt)).scalars())


@router.get("/employees/{employee_id}", response_model=UserOut)
async def get_employee(employee_id: int, db: DB, user=DashUser):
    svc = TenantService(db, user)
    target = await svc.assert_user_in_tenant(employee_id)
    if not svc.can_view_employee(target):
        raise HTTPException(status_code=403, detail="Not allowed for this employee")
    return target


@router.patch("/employees/{employee_id}", response_model=UserOut)
async def update_employee(employee_id: int, data: EmployeeAdminUpdate, db: DB,
                          user=Depends(require_role([ROLE_OWNER]))):
    svc = TenantService(db, user)
    target = await svc.assert_user_in_tenant(employee_id)
    if data.full_name is not None:
        target.full_name = data.full_name
    if data.active is not None:
        target.active = data.active
    await db.flush()
    return target


@router.delete("/employees/{employee_id}", status_code=204)
async def deactivate_employee(employee_id: int, db: DB, user=Depends(require_role([ROLE_OWNER]))):
    svc = TenantService(db, user)
    target = await svc.assert_user_in_tenant(employee_id)
    target.active = False  # soft-delete (see open retention question in API doc)
    await db.flush()
    return None


@router.patch("/employees/{employee_id}/role", response_model=UserOut)
async def change_role(employee_id: int, data: RoleUpdate, db: DB, user=Depends(require_role([ROLE_OWNER]))):
    if data.role not in ("owner_admin", "manager", "employee"):
        raise HTTPException(status_code=400, detail="Invalid role")
    svc = TenantService(db, user)
    target = await svc.assert_user_in_tenant(employee_id)
    target.role = data.role
    await db.flush()
    return target


@router.patch("/employees/{employee_id}/team", response_model=UserOut)
async def change_team(employee_id: int, data: TeamAssign, db: DB, user=Depends(require_role([ROLE_OWNER]))):
    svc = TenantService(db, user)
    target = await svc.assert_user_in_tenant(employee_id)
    if data.team_id is not None:
        team = await db.get(Team, data.team_id)
        if team is None or team.company_id != user.company_id:
            raise HTTPException(status_code=404, detail="Team not found")
    target.team_id = data.team_id
    await db.flush()
    return target


@router.patch("/employees/{employee_id}/timezone", response_model=UserOut)
async def change_timezone(employee_id: int, data: TimezoneUpdate, db: DB, user=Depends(require_role([ROLE_OWNER]))):
    """New: per-employee timezone override. Empty string / null clears the
    override, falling back to the company's own timezone (see
    AttendanceService.shift_status() and OvertimeService.start(), both of
    which already read User.timezone with this exact fallback)."""
    svc = TenantService(db, user)
    target = await svc.assert_user_in_tenant(employee_id)
    target.timezone = data.timezone or None
    await db.flush()
    return target


@router.patch("/employees/{employee_id}/holiday-country", response_model=UserOut)
async def change_holiday_country(employee_id: int, data: HolidayCountryUpdate, db: DB,
                                 user=Depends(require_role([ROLE_OWNER]))):
    """New: which country's holiday calendar this employee follows. Empty
    string / null clears it entirely (no holiday calendar at all for this
    employee -- regular check-in is never blocked for holidays, and health
    reminders never pause for holidays, for this specific person)."""
    svc = TenantService(db, user)
    target = await svc.assert_user_in_tenant(employee_id)
    target.holiday_country = data.holiday_country or None
    await db.flush()
    return target


@router.patch("/employees/{employee_id}/job-type", response_model=UserOut)
async def change_job_type(employee_id: int, data: JobTypeUpdate, db: DB,
                          user=Depends(require_role([ROLE_OWNER]))):
    """New: full_time keeps the existing shift-based check-in/out flow
    unchanged. part_time removes shift-time restrictions but limits the
    employee to one check-in/out cycle per day (see
    AttendanceService.check_in())."""
    if data.job_type not in ("full_time", "part_time"):
        raise HTTPException(status_code=400, detail="job_type must be 'full_time' or 'part_time'")
    svc = TenantService(db, user)
    target = await svc.assert_user_in_tenant(employee_id)
    target.job_type = data.job_type
    await db.flush()
    return target


@router.patch("/employees/{employee_id}/actual-working-hours", response_model=UserOut)
async def change_actual_working_hours(employee_id: int, data: ActualWorkingHoursUpdate, db: DB,
                                      user=Depends(require_role([ROLE_OWNER]))):
    """New: which invoice calculation mode applies to this employee -- True
    sums real clocked hours (minus breaks/deductions), False assumes full
    scheduled hours per workday minus approved leave only. See
    InvoiceService for the actual calculation logic."""
    svc = TenantService(db, user)
    target = await svc.assert_user_in_tenant(employee_id)
    target.actual_working_hours = data.actual_working_hours
    await db.flush()
    return target


@router.patch("/employees/{employee_id}/hourly-fee", response_model=UserOut)
async def change_hourly_fee(employee_id: int, data: HourlyFeeUpdate, db: DB,
                            user=Depends(require_role([ROLE_OWNER]))):
    """New: an employee's hourly rate for invoicing. Only meaningful once
    the company has invoicing enabled (Settings > Invoicing), but can be
    set ahead of time regardless -- generate_invoices_for_company() simply
    skips anyone with hourly_fee still null."""
    if data.hourly_fee is not None and data.hourly_fee < 0:
        raise HTTPException(status_code=400, detail="hourly_fee can't be negative")
    svc = TenantService(db, user)
    target = await svc.assert_user_in_tenant(employee_id)
    target.hourly_fee = data.hourly_fee
    await db.flush()
    return target


@router.patch("/employees/{employee_id}/language", response_model=UserOut)
async def change_language(employee_id: int, data: LanguageUpdate, db: DB,
                          user=Depends(require_role([ROLE_OWNER]))):
    """New: employee's preferred UI language for mobile/portal. Unlike
    timezone/holiday_country, there's no clear-to-null case here -- "en"
    IS the fallback value itself, so every value must be one of the
    supported codes."""
    if data.language not in ("en", "ja", "ko", "zh", "hi"):
        raise HTTPException(status_code=400, detail="Unsupported language")
    svc = TenantService(db, user)
    target = await svc.assert_user_in_tenant(employee_id)
    target.language = data.language
    await db.flush()
    return target


@router.get("/teams", response_model=list[TeamOut])
async def list_teams(db: DB, user=DashUser):
    svc = TenantService(db, user)
    return list((await db.execute(svc.tenant_select(Team))).scalars())


@router.post("/teams", response_model=TeamOut, status_code=201)
async def create_team(data: TeamCreate, db: DB, user=Depends(require_role([ROLE_OWNER]))):
    team = Team(company_id=user.company_id, name=data.name, manager_id=data.manager_id)
    db.add(team)
    await db.flush()
    return team


@router.patch("/teams/{team_id}", response_model=TeamOut)
async def update_team(team_id: int, data: TeamCreate, db: DB, user=Depends(require_role([ROLE_OWNER]))):
    team = await db.get(Team, team_id)
    if team is None or team.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="Team not found")
    team.name = data.name
    if data.manager_id is not None:
        team.manager_id = data.manager_id
    await db.flush()
    return team