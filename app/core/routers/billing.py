"""Billing — Stripe wiring. Flat, per-module pricing: no tiers, no seat
limits, no upgrade/downgrade between plans. A module is either enabled
(full price, full access) or disabled. Enabling starts a real billing
commitment for the current period; disabling only sets auto_renew=False --
access continues until current_period_end, then a scheduled job (not yet
built) flips status to "cancelled". Re-enabling before that period ends
just flips auto_renew back on, no new charge, since that period's already
paid for.

module_key is currently only ever "hr" -- this router is written
generically so Warehouse/POS slot in later without needing a rewrite.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.core.dependencies import DB, ROLE_OWNER, require_role
from app.integrations import stripe_client
from app.core.models.company import Company
from app.core.models.company_module import CompanyModule
from app.core.models.organization import Organization
from app.core.schemas.billing import CompanyModuleOut, EnableModuleRequest, ModuleOut

router = APIRouter(prefix="/billing", tags=["billing"])
Owner = Depends(require_role([ROLE_OWNER]))

CONFIRMED_STATUSES = ("active", "trialing")


class SetupIntentOut(BaseModel):
    client_secret: str


class PaymentMethodIn(BaseModel):
    payment_method_id: str


class PaymentMethodSummary(BaseModel):
    brand: str | None = None
    last4: str | None = None


@router.get("/modules", response_model=list[ModuleOut])
async def modules():
    """The flat-price catalog -- today just HR, Warehouse/POS append here later."""
    return stripe_client.MODULE_CATALOG


@router.get("/companies/me/modules", response_model=list[CompanyModuleOut])
async def my_company_modules(db: DB, user=Owner):
    """Every module row this company has (enabled, disabled, or never
    touched) -- powers a marketplace-style toggle list."""
    if user.company_id is None:
        raise HTTPException(status_code=409, detail="Create a company first.")
    res = await db.execute(select(CompanyModule).where(CompanyModule.company_id == user.company_id))
    return list(res.scalars())


async def _get_organization(db: DB, company: Company) -> Organization:
    org = await db.get(Organization, company.organization_id)
    if org is None:
        raise HTTPException(status_code=500, detail="Company has no organization on record")
    return org


@router.post("/modules/{module_key}/enable", response_model=CompanyModuleOut)
async def enable_module(module_key: str, db: DB, user=Owner, data: EnableModuleRequest = EnableModuleRequest()):
    if user.company_id is None:
        raise HTTPException(status_code=409, detail="Create a company first.")
    if module_key not in stripe_client.MODULE_PRICE_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown module '{module_key}'")

    company = await db.get(Company, user.company_id)
    organization = await _get_organization(db, company)

    res = await db.execute(select(CompanyModule).where(
        CompanyModule.company_id == user.company_id, CompanyModule.module_key == module_key,
    ))
    cm = res.scalar_one_or_none()
    if cm is None:
        cm = CompanyModule(company_id=user.company_id, module_key=module_key, status="incomplete")
        db.add(cm)
        await db.flush()

    # Already active and paid through a real future period -- re-enabling
    # is just "keep renewing," no new charge, nothing to do with Stripe.
    if cm.status in CONFIRMED_STATUSES and cm.auto_renew:
        return cm
    if cm.status in CONFIRMED_STATUSES and not cm.auto_renew:
        cm.auto_renew = True
        await db.flush()
        return cm

    if not organization.stripe_customer_id and stripe_client.stripe.api_key:
        organization.stripe_customer_id = stripe_client.create_customer(company.name, user.email)

    if stripe_client.stripe.api_key and stripe_client.MODULE_PRICE_IDS.get(module_key):
        stripe_sub = stripe_client.create_or_update_module_subscription(
            organization.stripe_customer_id, module_key,
            existing_subscription_id=cm.stripe_subscription_id,
            payment_method_id=data.payment_method_id,
        )
        cm.stripe_subscription_id = stripe_sub.id
        cm.status = stripe_sub.status
        if stripe_sub.status in CONFIRMED_STATUSES:
            cm.auto_renew = True
            period_end = getattr(stripe_sub, "current_period_end", None)
            cm.current_period_end = (
                datetime.fromtimestamp(period_end, tz=timezone.utc) if period_end
                else datetime.now(timezone.utc) + timedelta(days=30)
            )
    else:
        # Local dev without Stripe keys configured -- nothing to confirm,
        # just mark it active for a normal 30-day cycle.
        cm.status = "active"
        cm.auto_renew = True
        cm.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)

    await db.flush()
    return cm


@router.post("/modules/{module_key}/disable", response_model=CompanyModuleOut)
async def disable_module(module_key: str, db: DB, user=Owner):
    """Does NOT revoke access immediately and does NOT refund. Just stops
    the next renewal -- access continues until current_period_end."""
    res = await db.execute(select(CompanyModule).where(
        CompanyModule.company_id == user.company_id, CompanyModule.module_key == module_key,
    ))
    cm = res.scalar_one_or_none()
    if cm is None:
        raise HTTPException(status_code=404, detail=f"'{module_key}' isn't enabled for this company")
    cm.auto_renew = False
    if cm.stripe_subscription_id and stripe_client.stripe.api_key:
        try:
            # cancels at period end via Stripe's own setting where configured
            stripe_client.cancel_subscription(cm.stripe_subscription_id)
        except stripe_client.stripe.error.InvalidRequestError as exc:
            # "No such subscription" -- the stored ID is already gone on
            # Stripe's side (can happen after a database reset leaves a
            # stale ID, or if it was already cancelled directly in
            # Stripe's dashboard). The user's actual intent here is just
            # "stop auto-renewing," which is already true locally either
            # way -- don't let a missing remote record block that. Only
            # swallow this specific "already gone" case; a genuine
            # different Stripe error (auth failure, rate limit, etc.)
            # should still surface, not be silently eaten.
            if "No such subscription" not in str(exc):
                raise
    await db.flush()
    return cm


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, db: DB):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe_client.construct_webhook_event(payload, sig)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    obj = event["data"]["object"]

    if event["type"] in ("customer.subscription.updated", "customer.subscription.created"):
        await _sync_module_from_stripe_object(db, obj)

    elif event["type"] in ("invoice.payment_succeeded", "invoice_payment.paid"):
        subscription_id = obj.get("subscription")
        if subscription_id:
            fresh = stripe_client.stripe.Subscription.retrieve(subscription_id)
            await _sync_module_from_stripe_object(db, fresh)

    elif event["type"] == "customer.subscription.deleted":
        res = await db.execute(select(CompanyModule).where(CompanyModule.stripe_subscription_id == obj["id"]))
        cm = res.scalar_one_or_none()
        if cm:
            cm.status = "cancelled"
            cm.auto_renew = False
            await db.flush()

    return {"received": True}


async def _sync_module_from_stripe_object(db, stripe_obj) -> None:
    res = await db.execute(select(CompanyModule).where(CompanyModule.stripe_subscription_id == stripe_obj["id"]))
    cm = res.scalar_one_or_none()
    if not cm:
        return
    cm.status = stripe_obj["status"]
    period_end = stripe_obj.get("current_period_end")
    if period_end:
        cm.current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)
    await db.flush()


@router.get("/usage")
async def usage(db: DB, user=Owner):
    """Informational only now -- flat pricing has no seat limit, so
    seat_limit is always null. Kept for frontend compatibility until the
    HR Dashboard's old billing page (which called this) is removed."""
    if user.company_id is None:
        raise HTTPException(status_code=409, detail="Create a company first.")
    from sqlalchemy import func
    from app.core.models.user import User
    seats = await db.scalar(select(func.count(User.id)).where(
        User.company_id == user.company_id, User.active.is_(True)))
    return {"seats_used": seats or 0, "seat_limit": None}


@router.get("/invoices", response_model=list[dict])
async def invoices(db: DB, user=Owner):
    """Invoice list from Stripe for this company's Organization customer.
    Empty without Stripe keys.

    Returns a BARE ARRAY, not {"invoices": [...]}. This exact bug has
    regressed once already earlier in this project's history -- if you're
    reading this because InvoiceHistoryPage.tsx broke again with
    "invoices.data?.map is not a function", check this return statement
    first before looking anywhere else.
    """
    if user.company_id is None:
        raise HTTPException(status_code=409, detail="Create a company first.")
    company = await db.get(Company, user.company_id)
    organization = await _get_organization(db, company)
    if not (stripe_client.stripe.api_key and organization.stripe_customer_id):
        return []
    return stripe_client.list_invoices(organization.stripe_customer_id)


@router.get("/payment-method", response_model=PaymentMethodSummary)
async def get_payment_method(db: DB, user=Owner):
    if user.company_id is None:
        raise HTTPException(status_code=409, detail="Create a company first.")
    company = await db.get(Company, user.company_id)
    organization = await _get_organization(db, company)
    if not (stripe_client.stripe.api_key and organization.stripe_customer_id):
        return {"brand": None, "last4": None}
    customer = stripe_client.stripe.Customer.retrieve(organization.stripe_customer_id)
    default_pm_id = customer.invoice_settings.default_payment_method
    if not default_pm_id:
        return {"brand": None, "last4": None}
    pm = stripe_client.stripe.PaymentMethod.retrieve(default_pm_id)
    card = getattr(pm, "card", None)
    return {"brand": card.brand if card else None, "last4": card.last4 if card else None}


@router.post("/setup-intent", response_model=SetupIntentOut)
async def create_setup_intent(db: DB, user=Owner):
    """First step of adding/replacing a card, entirely in-dashboard via
    Stripe Elements -- no redirect to a Stripe-hosted page. Creates the
    Stripe customer lazily if this is the very first card this
    Organization has ever added (same lazy-creation pattern
    enable_module already uses)."""
    if user.company_id is None:
        raise HTTPException(status_code=409, detail="Create a company first.")
    if not stripe_client.stripe.api_key:
        raise HTTPException(status_code=409, detail="Billing isn't configured on this server yet.")

    company = await db.get(Company, user.company_id)
    organization = await _get_organization(db, company)
    if not organization.stripe_customer_id:
        organization.stripe_customer_id = stripe_client.create_customer(company.name, user.email)
        await db.flush()

    intent = stripe_client.create_setup_intent(organization.stripe_customer_id)
    return SetupIntentOut(client_secret=intent["client_secret"])


@router.patch("/payment-method", response_model=PaymentMethodSummary)
async def update_payment_method(data: PaymentMethodIn, db: DB, user=Owner):
    """Second step: called after the frontend has already confirmed the
    SetupIntent client-side with Stripe.js (stripe.confirmCardSetup --
    this is what actually handles 3DS/SCA if the card needs it). data
    carries the resulting payment_method id; this just attaches it and
    sets it as the customer's default for future module charges."""
    if user.company_id is None:
        raise HTTPException(status_code=409, detail="Create a company first.")
    if not stripe_client.stripe.api_key:
        raise HTTPException(status_code=409, detail="Billing isn't configured on this server yet.")

    company = await db.get(Company, user.company_id)
    organization = await _get_organization(db, company)
    if not organization.stripe_customer_id:
        raise HTTPException(status_code=409, detail="No Stripe customer on record yet -- call setup-intent first.")

    stripe_client.set_default_payment_method(organization.stripe_customer_id, data.payment_method_id)
    pm = stripe_client.stripe.PaymentMethod.retrieve(data.payment_method_id)
    card = getattr(pm, "card", None)
    return PaymentMethodSummary(brand=card.brand if card else None, last4=card.last4 if card else None)