"""Billing — Stripe wiring. plan_tier only ever changes once Stripe confirms
payment succeeded (subscribe/upgrade/downgrade set it optimistically ONLY on
active/trialing status; the webhook is the real source of truth going forward,
and explicitly falls back to 'startup' on cancellation rather than leaving
stale paid access in place)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from app.core.dependencies import DB, ROLE_OWNER, require_role
from app.integrations import stripe_client
from app.models.company import Company, Subscription
from app.schemas.billing import PlanOut, SubscribeRequest, SubscriptionOut

router = APIRouter(prefix="/billing", tags=["billing"])
Owner = Depends(require_role([ROLE_OWNER]))

CONFIRMED_STATUSES = ("active", "trialing")


@router.get("/plans", response_model=list[PlanOut])
async def plans():
    return stripe_client.PLAN_CATALOG


@router.get("/subscription", response_model=SubscriptionOut)
async def get_subscription(db: DB, user=Owner):
    sub = await _sub(db, user.company_id)
    return sub


@router.post("/subscribe", response_model=SubscriptionOut)
async def subscribe(data: SubscribeRequest, db: DB, user=Owner):
    if data.plan_tier not in ("startup", "mid", "enterprise"):
        raise HTTPException(status_code=400, detail="Unknown plan tier")

    sub = await _sub(db, user.company_id)
    company = await db.get(Company, user.company_id)
    was_confirmed_before = sub.status in CONFIRMED_STATUSES  # true for upgrade/downgrade on a real paying customer

    if not sub.stripe_customer_id and stripe_client.stripe.api_key:
        sub.stripe_customer_id = stripe_client.create_customer(company.name, user.email)

    if stripe_client.stripe.api_key and stripe_client.PLAN_PRICE_IDS.get(data.plan_tier):
        stripe_sub = stripe_client.create_or_update_subscription(
            sub.stripe_customer_id, data.plan_tier,
            existing_subscription_id=sub.stripe_subscription_id,
            payment_method_id=data.payment_method_id,
        )
        if stripe_sub.status in CONFIRMED_STATUSES:
            # Confirmed success -- commit the new status and plan_tier.
            sub.stripe_subscription_id = stripe_sub.id
            sub.status = stripe_sub.status
            sub.plan_tier = data.plan_tier
        elif was_confirmed_before:
            # Upgrade/downgrade attempt on an already-active subscription
            # that failed to confirm -- FULL fallback: leave status AND
            # plan_tier completely untouched, exactly as they were before
            # this attempt. This is the fix -- previously `status` alone
            # got clobbered to the failed state even when plan_tier stayed
            # protected, which could lock out an existing paying customer.
            pass
        else:
            # First-time subscribe that didn't confirm -- no prior "current
            # plan" to fall back to, so record the real attempt status
            # (e.g. "incomplete") for the UI to reflect honestly.
            sub.stripe_subscription_id = stripe_sub.id
            sub.status = stripe_sub.status
    else:
        sub.status = "active"
        sub.plan_tier = data.plan_tier  # local dev without Stripe keys — nothing to confirm

    await db.flush()
    return sub


@router.post("/upgrade", response_model=SubscriptionOut)
async def upgrade(data: SubscribeRequest, db: DB, user=Owner):
    return await subscribe(data, db, user)


@router.post("/downgrade", response_model=SubscriptionOut)
async def downgrade(data: SubscribeRequest, db: DB, user=Owner):
    return await subscribe(data, db, user)


@router.post("/cancel", response_model=SubscriptionOut)
async def cancel(db: DB, user=Owner):
    sub = await _sub(db, user.company_id)
    if stripe_client.stripe.api_key and sub.stripe_subscription_id:
        stripe_client.cancel_subscription(sub.stripe_subscription_id)
    sub.status = "canceled"
    sub.plan_tier = "startup"  # explicit fallback — no stale paid access after cancellation
    await db.flush()
    return sub


@router.get("/usage")
async def usage(db: DB, user=Owner):
    from sqlalchemy import func
    from app.models.users import User
    from app.integrations.stripe_client import SEAT_LIMITS
    seats = await db.scalar(select(func.count(User.id)).where(
        User.company_id == user.company_id, User.active.is_(True)))
    sub = await _sub(db, user.company_id)
    sub.seats_used = seats or 0
    await db.flush()
    return {"seats_used": sub.seats_used, "seat_limit": SEAT_LIMITS.get(sub.plan_tier),
            "plan_tier": sub.plan_tier}


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
        await _sync_subscription_from_stripe_object(db, obj)

    elif event["type"] in ("invoice.payment_succeeded", "invoice_payment.paid"):
        # A successful payment is the real source of truth that a plan is
        # now active -- don't rely solely on subscription.updated firing.
        # Pull the subscription ID off the invoice and re-fetch its current
        # state directly from Stripe to be certain.
        subscription_id = obj.get("subscription")
        if subscription_id:
            fresh = stripe_client.stripe.Subscription.retrieve(subscription_id)
            await _sync_subscription_from_stripe_object(db, fresh)

    elif event["type"] == "customer.subscription.deleted":
        res = await db.execute(select(Subscription).where(Subscription.stripe_subscription_id == obj["id"]))
        sub = res.scalar_one_or_none()
        if sub:
            sub.status = "canceled"
            sub.plan_tier = "startup"
            await db.flush()

    return {"received": True}


async def _sub(db, company_id: int) -> Subscription:
    res = await db.execute(select(Subscription).where(Subscription.company_id == company_id))
    sub = res.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="No subscription for company")
    return sub


@router.get("/invoices")
async def invoices(db: DB, user=Owner):
    """Invoice list from Stripe for this company's customer. Empty without Stripe keys."""
    sub = await _sub(db, user.company_id)
    if not (stripe_client.stripe.api_key and sub.stripe_customer_id):
        return {"invoices": [], "note": "Stripe not configured or no customer yet"}
    return {"invoices": stripe_client.list_invoices(sub.stripe_customer_id)}


@router.patch("/payment-method")
async def update_payment_method(db: DB, user=Owner, payload: dict = {}):
    """Two-step payment-method update:
    1. PATCH with {} -> returns a SetupIntent client_secret; client confirms it with card details.
    2. PATCH with {"payment_method_id": "pm_..."} -> attach + set as the customer's default.
    """
    sub = await _sub(db, user.company_id)
    if not stripe_client.stripe.api_key:
        return {"ok": True, "note": "Stripe not configured; no-op in local dev"}
    if not sub.stripe_customer_id:
        company = await db.get(Company, user.company_id)
        sub.stripe_customer_id = stripe_client.create_customer(company.name, user.email)
        await db.flush()
    payment_method_id = payload.get("payment_method_id")
    if not payment_method_id:
        return stripe_client.create_setup_intent(sub.stripe_customer_id)
    stripe_client.set_default_payment_method(sub.stripe_customer_id, payment_method_id)
    return {"ok": True}

async def _sync_subscription_from_stripe_object(db, stripe_obj) -> None:
    res = await db.execute(select(Subscription).where(Subscription.stripe_subscription_id == stripe_obj["id"]))
    sub = res.scalar_one_or_none()
    if not sub:
        return
    sub.status = stripe_obj["status"]
    if stripe_obj["status"] in CONFIRMED_STATUSES:
        price_id = stripe_obj["items"]["data"][0]["price"]["id"]
        tier = stripe_client.PRICE_TO_TIER.get(price_id)
        if tier:
            sub.plan_tier = tier
    await db.flush()