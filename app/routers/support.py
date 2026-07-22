"""Customer-facing support ticket submission -- the other half of
SupportTicket. This one IS normal tenant-scoped customer auth (CurrentUser,
Owner-only), unlike everything in app/routers/admin.py. A company reaching
out TO the platform, not platform staff reaching into a company."""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.dependencies import DB, ROLE_OWNER, CurrentUser, RequireActivePlan
from app.models.company import SupportTicket

router = APIRouter(prefix="/support", tags=["support"], dependencies=[RequireActivePlan])


@router.post("/tickets", status_code=201)
async def create_ticket(payload: dict, user: CurrentUser, db: DB):
    if user.role != ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Only the company owner can submit support tickets")

    subject = (payload.get("subject") or "").strip()
    message = (payload.get("message") or "").strip()
    if not subject or not message:
        raise HTTPException(status_code=400, detail="Subject and message are required")

    ticket = SupportTicket(
        company_id=user.company_id, submitted_by_user_id=user.id,
        subject=subject, message=message, status="open",
    )
    db.add(ticket)
    await db.flush()
    return {"id": ticket.id, "status": ticket.status}


@router.get("/tickets/me")
async def my_company_tickets(user: CurrentUser, db: DB):
    """Any employee can see their own company's ticket history (read-only) --
    not just the Owner who happened to submit each one."""
    rows = (await db.execute(
        select(SupportTicket).where(SupportTicket.company_id == user.company_id)
        .order_by(SupportTicket.created_at.desc())
    )).scalars().all()
    return [
        {"id": t.id, "subject": t.subject, "message": t.message, "status": t.status,
         "created_at": t.created_at, "resolved_at": t.resolved_at}
        for t in rows
    ]