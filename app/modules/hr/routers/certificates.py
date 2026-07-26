from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.core.config import settings as app_settings
from app.core.dependencies import (DB, ROLE_MANAGER, ROLE_OWNER, CurrentUser,
                                   require_role, RequireActivePlan)
from app.core.services.base import TenantService

DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))
Owner = Depends(require_role([ROLE_OWNER]))

certificates_router = APIRouter(prefix="/certificates", tags=["certificates"], dependencies=[RequireActivePlan])


@certificates_router.get("/me")
async def my_certificates(user: CurrentUser, db: DB):
    from app.modules.hr.models.misc import Certificate
    rows = (await db.execute(select(Certificate).where(Certificate.user_id == user.id)
                             .order_by(Certificate.issued_at.desc()))).scalars()
    return [{"id": c.id, "period_type": c.period_type, "period_start": str(c.period_start),
             "period_end": str(c.period_end), "pdf_url": c.pdf_url} for c in rows]


@certificates_router.get("")
async def list_certificates(db: DB, employee_id: int | None = None, user=DashUser):
    from app.modules.hr.models.misc import Certificate
    svc = TenantService(db, user)
    stmt = svc.tenant_select_via_user(Certificate).order_by(Certificate.issued_at.desc())
    if employee_id:
        target = await svc.assert_user_in_tenant(employee_id)
        if not svc.can_view_employee(target):
            raise HTTPException(status_code=403, detail="Not allowed for this employee")
        stmt = stmt.where(Certificate.user_id == employee_id)
    rows = (await db.execute(stmt)).scalars()
    return [{"id": c.id, "user_id": c.user_id, "period_type": c.period_type,
             "pdf_url": c.pdf_url, "issued_at": c.issued_at} for c in rows]


@certificates_router.get("/{certificate_id}/download")
async def download_certificate(certificate_id: int, db: DB, user: CurrentUser):
    """Serve the stored certificate file.

    The issuance task (workers/tasks/certificates.py) stores where the rendered
    file lives in `pdf_url`: a local path under UPLOAD_DIR is streamed back, an
    http(s) URL gets a redirect. Until a PDF renderer is wired into the task,
    pdf_url is None and this returns 409 so clients can distinguish
    "not generated yet" from "doesn't exist".
    """
    import os
    from fastapi.responses import FileResponse, RedirectResponse
    from app.modules.hr.models.misc import Certificate

    cert = await db.get(Certificate, certificate_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificate not found")

    svc = TenantService(db, user)
    owner = await svc.assert_user_in_tenant(cert.user_id)  # 404 if cross-tenant
    if cert.user_id != user.id and not svc.can_view_employee(owner):
        raise HTTPException(status_code=404, detail="Certificate not found")

    if not cert.pdf_url:
        raise HTTPException(status_code=409, detail="Certificate file not generated yet")
    if cert.pdf_url.startswith(("http://", "https://")):
        return RedirectResponse(cert.pdf_url)
    # Local file: only serve from inside UPLOAD_DIR (no path traversal).
    path = os.path.realpath(cert.pdf_url)
    upload_root = os.path.realpath(app_settings.UPLOAD_DIR)
    if not path.startswith(upload_root + os.sep) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Certificate file missing")
    return FileResponse(path, filename=f"certificate_{cert.period_type}_{cert.period_start}.pdf")
