"""Internal platform-admin API. Every endpoint here is gated by CurrentAdmin
(app/core/admin_auth.py), NOT the customer CurrentUser -- these deliberately
bypass all tenant scoping, since the entire point is cross-company
visibility. Never import or reuse TenantService/tenant_select here.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.core.admin_auth import CurrentAdmin
from app.core.dependencies import DB
from app.integrations import stripe_client
from app.models.company import Company, Subscription, SupportTicket
from app.models.users import User

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------- companies ----------
@router.get("/companies")
async def list_companies(db: DB, admin: CurrentAdmin, search: str | None = None):
    stmt = select(Company)
    if search:
        stmt = stmt.where(Company.name.ilike(f"%{search}%"))
    companies = (await db.execute(stmt.order_by(Company.created_at.desc()))).scalars().all()

    out = []
    for company in companies:
        sub = (await db.execute(
            select(Subscription).where(Subscription.company_id == company.id)
        )).scalar_one_or_none()
        employee_count = await db.scalar(
            select(func.count(User.id)).where(User.company_id == company.id, User.active.is_(True))
        )
        out.append({
            "id": company.id,
            "name": company.name,
            "industry": company.industry,
            "active": company.active,
            "created_at": company.created_at,
            "employee_count": employee_count or 0,
            "plan_tier": sub.plan_tier if sub else None,
            "subscription_status": sub.status if sub else "none",
            "renews_at": sub.renews_at if sub else None,
        })
    return out


@router.get("/companies/{company_id}")
async def get_company(company_id: int, db: DB, admin: CurrentAdmin):
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    sub = (await db.execute(
        select(Subscription).where(Subscription.company_id == company_id)
    )).scalar_one_or_none()
    employees = (await db.execute(
        select(User).where(User.company_id == company_id).order_by(User.role, User.full_name)
    )).scalars().all()

    invoices = []
    if sub and sub.stripe_customer_id and stripe_client.stripe.api_key:
        try:
            invoices = stripe_client.list_invoices(sub.stripe_customer_id)
        except Exception:
            invoices = []  # Stripe hiccup shouldn't break the whole detail page

    return {
        "id": company.id,
        "name": company.name,
        "industry": company.industry,
        "timezone": company.timezone,
        "active": company.active,
        "created_at": company.created_at,
        "subscription": None if sub is None else {
            "plan_tier": sub.plan_tier,
            "status": sub.status,
            "seats_used": sub.seats_used,
            "renews_at": sub.renews_at,
            "started_at": sub.created_at,
            "stripe_customer_id": sub.stripe_customer_id,
        },
        "employees": [
            {"id": e.id, "email": e.email, "full_name": e.full_name, "role": e.role,
             "active": e.active, "joined_at": e.joined_at}
            for e in employees
        ],
        "invoices": invoices,
    }


@router.patch("/companies/{company_id}/active")
async def set_company_active(company_id: int, payload: dict, db: DB, admin: CurrentAdmin):
    """The manual kill switch -- independent of Stripe/subscription status
    entirely (enforced in require_active_subscription(), which checks this
    flag FIRST before ever looking at the subscription)."""
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    active = payload.get("active")
    if not isinstance(active, bool):
        raise HTTPException(status_code=400, detail="'active' must be true or false")
    company.active = active
    await db.flush()
    return {"id": company.id, "active": company.active}


# ---------- support tickets ----------
@router.get("/tickets")
async def list_tickets(db: DB, admin: CurrentAdmin, status_filter: str | None = None, company_id: int | None = None):
    stmt = select(SupportTicket, Company.name).join(Company, Company.id == SupportTicket.company_id)
    if status_filter:
        stmt = stmt.where(SupportTicket.status == status_filter)
    if company_id:
        stmt = stmt.where(SupportTicket.company_id == company_id)
    rows = (await db.execute(stmt.order_by(SupportTicket.created_at.desc()))).all()
    return [
        {"id": t.id, "company_id": t.company_id, "company_name": company_name,
         "subject": t.subject, "message": t.message, "status": t.status,
         "created_at": t.created_at, "resolved_at": t.resolved_at}
        for t, company_name in rows
    ]


@router.patch("/tickets/{ticket_id}")
async def update_ticket(ticket_id: int, payload: dict, db: DB, admin: CurrentAdmin):
    ticket = await db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    new_status = payload.get("status")
    if new_status not in ("open", "in_progress", "resolved"):
        raise HTTPException(status_code=400, detail="status must be open, in_progress, or resolved")
    ticket.status = new_status
    if new_status == "resolved":
        ticket.resolved_at = datetime.now(timezone.utc)
        ticket.resolved_by_admin_id = admin.id
    await db.flush()
    return {"id": ticket.id, "status": ticket.status}