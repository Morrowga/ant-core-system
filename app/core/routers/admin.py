"""Internal platform-admin API. Every endpoint here is gated by CurrentAdmin
(app/core/admin_auth.py), NOT the customer CurrentUser -- these deliberately
bypass all tenant scoping, since the entire point is cross-company
visibility. Never import or reuse TenantService/tenant_select here.

Reads CompanyModule (per-module status) instead of the legacy single
Subscription row -- Subscription has no module_key column at all, so it
literally cannot represent a company running more than one module, which
is the entire point of this platform. Organization is now surfaced too
(name + owner email), since Company no longer stands alone the way it
did before the Organization/Company split.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.core.admin_auth import CurrentAdmin
from app.core.dependencies import DB
from app.integrations import stripe_client
from app.core.models.company import Company, SupportTicket
from app.core.models.company_module import CompanyModule
from app.core.models.organization import Organization
from app.core.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------- organizations (the actual platform-level entity) ----------
@router.get("/organizations")
async def list_organizations(db: DB, admin: CurrentAdmin, search: str | None = None):
    stmt = select(Organization)
    if search:
        stmt = stmt.where(Organization.name.ilike(f"%{search}%"))
    organizations = (await db.execute(stmt.order_by(Organization.created_at.desc()))).scalars().all()

    out = []
    for org in organizations:
        owner = await db.get(User, org.owner_user_id) if org.owner_user_id else None
        company_count = await db.scalar(
            select(func.count(Company.id)).where(Company.organization_id == org.id)
        )
        out.append({
            "id": org.id,
            "name": org.name,
            "owner_email": owner.email if owner else None,
            "company_count": company_count or 0,
            "created_at": org.created_at,
        })
    return out


@router.get("/organizations/{organization_id}")
async def get_organization(organization_id: int, db: DB, admin: CurrentAdmin):
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    owner = await db.get(User, organization.owner_user_id) if organization.owner_user_id else None
    company_count = await db.scalar(
        select(func.count(Company.id)).where(Company.organization_id == organization_id)
    )

    return {
        "id": organization.id,
        "name": organization.name,
        "owner_email": owner.email if owner else None,
        "owner_id": organization.owner_user_id,
        "stripe_customer_id": organization.stripe_customer_id,
        "created_at": organization.created_at,
        "company_count": company_count or 0,
    }


# ---------- companies (drill-down FROM an organization, not the top-level view anymore) ----------
@router.get("/companies")
async def list_companies(db: DB, admin: CurrentAdmin, search: str | None = None):
    stmt = select(Company)
    if search:
        stmt = stmt.where(Company.name.ilike(f"%{search}%"))
    companies = (await db.execute(stmt.order_by(Company.created_at.desc()))).scalars().all()

    out = []
    for company in companies:
        organization = await db.get(Organization, company.organization_id)
        modules = (await db.execute(
            select(CompanyModule).where(CompanyModule.company_id == company.id)
        )).scalars().all()
        employee_count = await db.scalar(
            select(func.count(User.id)).where(User.company_id == company.id, User.active.is_(True))
        )
        active_modules = [m for m in modules if m.status in ("active", "trialing")]
        out.append({
            "id": company.id,
            "name": company.name,
            "industry": company.industry,
            "active": company.active,
            "created_at": company.created_at,
            "employee_count": employee_count or 0,
            "organization_id": company.organization_id,
            "organization_name": organization.name if organization else None,
            "modules_enabled": len(active_modules),
            "modules": [{"module_key": m.module_key, "status": m.status} for m in modules],
        })
    return out


@router.get("/companies/{company_id}")
async def get_company(company_id: int, db: DB, admin: CurrentAdmin):
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    organization = await db.get(Organization, company.organization_id)
    modules = (await db.execute(
        select(CompanyModule).where(CompanyModule.company_id == company_id)
    )).scalars().all()
    employees = (await db.execute(
        select(User).where(User.company_id == company_id).order_by(User.role, User.full_name)
    )).scalars().all()

    invoices = []
    if organization and organization.stripe_customer_id and stripe_client.stripe.api_key:
        try:
            invoices = stripe_client.list_invoices(organization.stripe_customer_id)
        except Exception:
            invoices = []  # Stripe hiccup shouldn't break the whole detail page

    return {
        "id": company.id,
        "name": company.name,
        "industry": company.industry,
        "timezone": company.timezone,
        "active": company.active,
        "created_at": company.created_at,
        "organization": None if organization is None else {
            "id": organization.id,
            "name": organization.name,
            "stripe_customer_id": organization.stripe_customer_id,
        },
        "modules": [
            {
                "module_key": m.module_key, "status": m.status, "seats_used": m.seats_used,
                "auto_renew": m.auto_renew, "current_period_end": m.current_period_end,
                "stripe_subscription_id": m.stripe_subscription_id,
            }
            for m in modules
        ],
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
    entirely (enforced in require_module_enabled(), which checks this
    flag FIRST before ever looking at module status)."""
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