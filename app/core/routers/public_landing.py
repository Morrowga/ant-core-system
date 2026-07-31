"""Public landing-page forms -- Contact and Support ticket, both reachable
by anyone visiting the marketing site, no login required.

DELIBERATELY SEPARATE from app/core/routers/support.py -- that router's
POST /support/tickets is for an already-logged-in company Owner with an
active plan, submitting a ticket about their own account. This one is for
a completely different audience: an anonymous visitor (prospective
customer, or an existing customer who doesn't want to log in first) with
no company/tenant context at all. Reusing the SupportTicket model here
wouldn't fit -- it's built around company_id/submitted_by_user_id, neither
of which exists for an anonymous submission. These just send an email
instead of writing a DB row.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.integrations import landing_email

router = APIRouter(prefix="/public", tags=["public"])


class ContactFormIn(BaseModel):
    name: str = Field(min_length=2)
    email: EmailStr
    message: str = Field(min_length=10)


class SupportTicketFormIn(BaseModel):
    subject: str = Field(min_length=3)
    message: str = Field(min_length=10)


@router.post("/contact", status_code=201)
async def submit_contact_form(payload: ContactFormIn):
    try:
        landing_email.send_contact_form_email(payload.name, payload.email, payload.message)
    except Exception as exc:
        # Don't leak SMTP internals to an anonymous caller -- but do fail
        # loudly server-side (via the raised 502) so a broken mail config
        # is actually noticed rather than silently swallowed.
        raise HTTPException(status_code=502, detail="Could not send message right now.") from exc
    return {"sent": True}


@router.post("/support", status_code=201)
async def submit_support_form(payload: SupportTicketFormIn):
    try:
        landing_email.send_support_ticket_email(payload.subject, payload.message)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Could not send message right now.") from exc
    return {"sent": True}