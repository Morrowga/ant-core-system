"""Stripe wrapper — billing skeleton."""
import stripe

from app.core.config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

PLAN_PRICE_IDS = {
    "startup": settings.STRIPE_PRICE_STARTUP,
    "mid": settings.STRIPE_PRICE_MID,
    "enterprise": settings.STRIPE_PRICE_ENTERPRISE,
}
PRICE_TO_TIER = {v: k for k, v in PLAN_PRICE_IDS.items() if v}

SEAT_LIMITS = {"startup": 20, "mid": 100, "enterprise": None}  # None = unlimited
PLAN_CATALOG = [
    {"tier": "startup", "name": "Startup", "price_monthly_usd": 49,
     "seat_limit": 20,
     "features": ["attendance", "reports", "health-self", "knowledge", "feedback",
                  "certificates", "alerts customization", "goals"]},
    {"tier": "mid", "name": "Mid", "price_monthly_usd": 149,
     "seat_limit": 100,
     "features": ["everything in Startup", "AI workload analysis", "ask-your-company",
                  "work-thread matching"]},
    {"tier": "enterprise", "name": "Enterprise", "price_monthly_usd": 399,
     "seat_limit": None,
     "features": ["everything in Mid", "unlimited seats", "priority support"]},
]

def create_customer(company_name: str, email: str) -> str:
    customer = stripe.Customer.create(name=company_name, email=email)
    return customer.id


def attach_payment_method(customer_id: str, payment_method_id: str) -> None:
    stripe.PaymentMethod.attach(payment_method_id, customer=customer_id)
    stripe.Customer.modify(customer_id, invoice_settings={"default_payment_method": payment_method_id})


def create_or_update_subscription(
    customer_id: str,
    plan_tier: str,
    existing_subscription_id: str | None = None,
    payment_method_id: str | None = None,
) -> "stripe.Subscription":
    price_id = PLAN_PRICE_IDS.get(plan_tier)
    if not price_id:
        raise ValueError(f"No Stripe price configured for tier '{plan_tier}'")

    if payment_method_id:
        attach_payment_method(customer_id, payment_method_id)

    if existing_subscription_id:
        current = stripe.Subscription.retrieve(existing_subscription_id)
        if current.status not in ("incomplete", "incomplete_expired", "canceled"):
            sub = stripe.Subscription.modify(
                existing_subscription_id,
                items=[{"id": current["items"]["data"][0].id, "price": price_id}],
                proration_behavior="create_prorations",
            )
            return _try_confirm_latest_invoice(sub, customer_id)
        if current.status == "incomplete":
            stripe.Subscription.cancel(existing_subscription_id)

    sub = stripe.Subscription.create(
        customer=customer_id, items=[{"price": price_id}],
        payment_behavior="default_incomplete",
    )
    return _try_confirm_latest_invoice(sub, customer_id)


def _try_confirm_latest_invoice(sub: "stripe.Subscription", customer_id: str) -> "stripe.Subscription":
    """default_incomplete creates the invoice/PaymentIntent but never confirms
    it automatically — this actually charges the customer's default payment
    method, using the card already saved via the SetupIntent flow.

    No off_session=True here: subscription invoice PaymentIntents already have
    setup_future_usage set by Stripe, and passing off_session at the same time
    is rejected outright. Confirming with just payment_method is correct.
    """
    if sub.status != "incomplete":
        return sub
    invoice = stripe.Invoice.retrieve(sub.latest_invoice, expand=["payment_intent"])
    pi = invoice.payment_intent
    if pi is None or pi.status != "requires_confirmation":
        return sub
    customer = stripe.Customer.retrieve(customer_id)
    default_pm = customer.invoice_settings.default_payment_method
    if not default_pm:
        return sub  # genuinely nothing to charge — stays incomplete, which is correct

    try:
        stripe.PaymentIntent.confirm(pi.id, payment_method=default_pm)
    except stripe.error.StripeError:
        pass  # decline, requires 3DS, or any other Stripe-side rejection —
              # leave it incomplete, the caller's status field already reflects that
    return stripe.Subscription.retrieve(sub.id)  # re-fetch to get the now-current status

def cancel_subscription(subscription_id: str) -> "stripe.Subscription":
    return stripe.Subscription.cancel(subscription_id)


def construct_webhook_event(payload: bytes, sig_header: str):
    return stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)


def list_invoices(customer_id: str, limit: int = 24) -> list[dict]:
    invoices = stripe.Invoice.list(customer=customer_id, limit=limit)
    return [{
        "id": inv.id,
        "number": inv.number,
        "status": inv.status,
        "amount_due": inv.amount_due,
        "amount_paid": inv.amount_paid,
        "currency": inv.currency,
        "created": inv.created,
        "hosted_invoice_url": inv.hosted_invoice_url,
        "invoice_pdf": inv.invoice_pdf,
    } for inv in invoices.auto_paging_iter()]


def create_setup_intent(customer_id: str) -> dict:
    """SetupIntent flow: client confirms it with card details, then we attach the
    resulting payment method as the customer's default via attach_payment_method."""
    intent = stripe.SetupIntent.create(customer=customer_id, usage="off_session")
    return {"setup_intent_id": intent.id, "client_secret": intent.client_secret}


def set_default_payment_method(customer_id: str, payment_method_id: str) -> None:
    attach_payment_method(customer_id, payment_method_id)