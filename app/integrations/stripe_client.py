"""Stripe wrapper — billing skeleton.

Flat, per-module pricing: every company pays the same amount for a given
module (no Startup/Mid/Enterprise tiers, no seat limits). MODULE_PRICE_IDS
maps a module_key straight to one Stripe Price id. Adding a new module
later (Warehouse, POS) is just one more entry here plus one more row in
MODULE_CATALOG -- no tier logic anywhere to extend.
"""
import stripe

from app.core.config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

MODULE_PRICE_IDS = {
    "hr": settings.STRIPE_PRICE_HR,
    "warehouse": settings.STRIPE_PRICE_WAREHOUSE,
}
PRICE_TO_MODULE = {v: k for k, v in MODULE_PRICE_IDS.items() if v}

MODULE_CATALOG = [
    {"module_key": "hr", "name": "Office HR", "price_monthly_usd": 80,
     "description": "Attendance, reports, health, knowledge, feedback, certificates, "
                     "alerts, AI insights, projects & invoicing -- one flat price, everything included."},
    {"module_key": "warehouse", "name": "Warehouse", "price_monthly_usd": 40,
     "description": "Inventory, stock movements, and warehouse operations -- one flat price."},
]


def create_customer(company_name: str, email: str) -> str:
    customer = stripe.Customer.create(name=company_name, email=email)
    return customer.id


def attach_payment_method(customer_id: str, payment_method_id: str) -> None:
    stripe.PaymentMethod.attach(payment_method_id, customer=customer_id)
    stripe.Customer.modify(customer_id, invoice_settings={"default_payment_method": payment_method_id})


def create_or_update_module_subscription(
    customer_id: str,
    module_key: str,
    existing_subscription_id: str | None = None,
    payment_method_id: str | None = None,
) -> "stripe.Subscription":
    price_id = MODULE_PRICE_IDS.get(module_key)
    if not price_id:
        raise ValueError(f"No Stripe price configured for module '{module_key}'")

    if payment_method_id:
        attach_payment_method(customer_id, payment_method_id)

    if existing_subscription_id:
        current = stripe.Subscription.retrieve(existing_subscription_id)
        if current.status not in ("incomplete", "incomplete_expired", "canceled"):
            # Already has a subscription for this module and it's in a
            # real state -- nothing to change price-wise since there's
            # only ever one price per module now. Just return it as-is.
            return current

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