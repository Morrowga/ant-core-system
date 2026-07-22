from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import (DB, ROLE_MANAGER, ROLE_OWNER, require_plan_feature,
                                   require_role, RequireActivePlan)
from app.services.base import TenantService

DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))
Owner = Depends(require_role([ROLE_OWNER]))

alerts_router = APIRouter(prefix="/alerts", tags=["alerts"], dependencies=[RequireActivePlan])


@alerts_router.get("")
async def list_alerts(db: DB, type: str | None = None, status: str | None = None,
                      employee_id: int | None = None, user=DashUser):
    from app.models.misc import Alert
    svc = TenantService(db, user)
    stmt = svc.tenant_select(Alert).order_by(Alert.created_at.desc()).limit(500)
    if type:
        stmt = stmt.where(Alert.type == type)
    if status:
        stmt = stmt.where(Alert.status == status)
    if employee_id:
        target = await svc.assert_user_in_tenant(employee_id)
        if not svc.can_view_employee(target):
            raise HTTPException(status_code=403, detail="Not allowed for this employee")
        stmt = stmt.where(Alert.user_id == employee_id)
    rows = (await db.execute(stmt)).scalars()
    return [{"id": a.id, "user_id": a.user_id, "type": a.type, "status": a.status,
             "created_at": a.created_at, "escalated_at": a.escalated_at} for a in rows]


@alerts_router.patch("/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int, db: DB, user=DashUser):
    from app.models.misc import Alert
    alert = await db.get(Alert, alert_id)
    if alert is None or alert.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = "acknowledged"
    await db.flush()
    return {"ok": True}


@alerts_router.get("/settings")
async def get_alert_settings(db: DB, user=DashUser):
    from app.models.misc import AlertSetting
    svc = TenantService(db, user)
    rows = (await db.execute(svc.tenant_select(AlertSetting))).scalars()
    return {"alert_types": [
        {"type": s.type, "enabled": s.enabled,
         "escalation_delay_minutes": s.escalation_delay_minutes,
         "notify_roles": s.notify_roles} for s in rows
    ]}


@alerts_router.patch("/settings")
async def patch_alert_settings(payload: dict, db: DB, user=Owner):
    from app.models.misc import AlertSetting
    svc = TenantService(db, user)
    for entry in payload.get("alert_types", []):
        row = (await db.execute(svc.tenant_select(AlertSetting)
                                .where(AlertSetting.type == entry.get("type", "")))).scalar_one_or_none()
        if row is None:
            row = AlertSetting(company_id=user.company_id, type=entry.get("type", "generic"))
            db.add(row)
        for f in ("enabled", "escalation_delay_minutes", "notify_roles"):
            if f in entry:
                setattr(row, f, entry[f])
    await db.flush()
    return {"ok": True}


