"""Invoicing endpoints. Generation is manual and queued (see
app/workers/tasks/invoices.py) -- POST /invoices/generate just enqueues the
task and returns immediately, it does not wait for generation to finish.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.core.dependencies import DB, ROLE_MANAGER, ROLE_OWNER, CurrentUser, RequireActivePlan, require_role
from app.modules.hr.services.invoices import InvoiceService

router = APIRouter(prefix="/invoices", tags=["invoices"], dependencies=[RequireActivePlan])
DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))


def _serialize(invoice) -> dict:
    return {
        "id": invoice.id, "user_id": invoice.user_id,
        "period_start": invoice.period_start, "period_end": invoice.period_end,
        "hourly_fee": invoice.hourly_fee, "total_hours": invoice.total_hours,
        "total_amount": invoice.total_amount, "actual_working_hours": invoice.actual_working_hours,
        "pdf_url": invoice.pdf_url, "generated_at": invoice.generated_at,
    }


@router.post("/generate")
async def generate_invoices(user: CurrentUser, db: DB, _owner=DashUser):
    """Owner/Manager-triggered. Enqueues the Celery task and returns
    immediately -- the button doesn't wait for every employee to be
    processed. Poll GET /invoices afterward to see results appear."""
    if user.role != "owner_admin":
        raise HTTPException(status_code=403, detail="Only the company owner can generate invoices")

    from app.core.models.company import CompanySettings
    settings_row = (await db.execute(select(CompanySettings).where(
        CompanySettings.company_id == user.company_id, CompanySettings.section == "invoicing",
    ))).scalar_one_or_none()
    if not settings_row or not settings_row.data_json.get("invoice_enabled", False):
        raise HTTPException(status_code=400, detail="Invoicing is not enabled in Settings")

    from app.modules.hr.workers.tasks.invoices import generate_invoices_for_company
    generate_invoices_for_company.delay(user.company_id)
    return {"queued": True}


@router.get("")
async def list_invoices(db: DB, employee_id: int | None = None, user=DashUser):
    svc = InvoiceService(db, user)
    rows = await svc.list_for_dashboard(employee_id)
    return [_serialize(r) for r in rows]


@router.get("/me")
async def my_invoices(user: CurrentUser, db: DB):
    svc = InvoiceService(db, user)
    rows = await svc.my_invoices()
    return [_serialize(r) for r in rows]


@router.get("/{invoice_id}")
async def get_invoice(invoice_id: int, user: CurrentUser, db: DB):
    svc = InvoiceService(db, user)
    invoice = await svc.get_one(invoice_id)
    return _serialize(invoice)