from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.core.dependencies import (DB, ROLE_MANAGER, ROLE_OWNER, CurrentUser,
                                   require_role, RequireActivePlan)
from app.models.misc import Recognition
from app.services.base import TenantService

DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))
Owner = Depends(require_role([ROLE_OWNER]))

recognitions_router = APIRouter(prefix="/recognitions", tags=["recognitions"], dependencies=[RequireActivePlan])


@recognitions_router.post("", status_code=201)
async def give_kudos(payload: dict, db: DB, user=DashUser):
    from app.services import notifications as notification_service
    svc = TenantService(db, user)
    target = await svc.assert_user_in_tenant(int(payload["employee_id"]))
    rec = Recognition(company_id=user.company_id, given_by=user.id, employee_id=target.id,
                      report_id=payload.get("report_id"), reason=payload.get("reason", ""))
    db.add(rec)
    await db.flush()
    await notification_service.send(db, target.id, "recognition", "You received kudos! 🎉",
                                    rec.reason[:200])
    return {"id": rec.id}


@recognitions_router.get("")
async def list_recognitions(db: DB, employee_id: int | None = None, user=DashUser):
    from app.models.users import User
    svc = TenantService(db, user)
    stmt = (
        select(Recognition, User.full_name)
        .join(User, User.id == Recognition.employee_id)
        .where(Recognition.company_id == user.company_id)
        .order_by(Recognition.created_at.desc())
        .limit(200)
    )
    if employee_id is not None:
        target = await svc.assert_user_in_tenant(employee_id)
        if not svc.can_view_employee(target):
            raise HTTPException(status_code=403, detail="Not allowed for this employee")
        stmt = stmt.where(Recognition.employee_id == employee_id)

    rows = (await db.execute(stmt)).all()
    return [
        {"id": r.id, "employee_id": r.employee_id, "employee_name": full_name,
         "given_by": r.given_by, "reason": r.reason, "created_at": r.created_at}
        for r, full_name in rows
    ]


@recognitions_router.get("/me")
async def my_recognitions(user: CurrentUser, db: DB):
    rows = (await db.execute(select(Recognition).where(Recognition.employee_id == user.id)
                             .order_by(Recognition.created_at.desc()))).scalars()
    return [{"id": r.id, "reason": r.reason, "created_at": r.created_at} for r in rows]