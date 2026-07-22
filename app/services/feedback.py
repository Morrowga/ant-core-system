"""Feedback/complaints. Enforces rules 9 (harassment -> owner-only, hardcoded)
and 10 (anonymous stays anonymous — user_id never stored, timestamp coarsened)."""

from fastapi import HTTPException
from sqlalchemy import select

from app.models.misc import FeedbackTicket
from app.services.base import TenantService

# Platform-locked. Deliberately NOT a company setting.
OWNER_ONLY_CATEGORIES = {"harassment"}


class FeedbackService(TenantService):
    async def create(self, category: str, message: str, anonymous: bool) -> FeedbackTicket:
        # New: actually checks the company's "Allow anonymous submissions"
        # setting before honoring the anonymous flag -- previously this
        # came straight from whatever the client sent, completely ignoring
        # whether the Owner had disabled the option.
        if anonymous:
            from app.models.company import CompanySettings
            row = (await self.db.execute(select(CompanySettings).where(
                CompanySettings.company_id == self.company_id, CompanySettings.section == "feedback",
            ))).scalar_one_or_none()
            allowed = row.data_json.get("anonymous_submissions_enabled", True) if row else True
            if not allowed:
                raise HTTPException(
                    status_code=403,
                    detail="Anonymous submissions are disabled by your company. Submit with your name instead.",
                )

        ticket = FeedbackTicket(
            company_id=self.company_id,
            # RULE 10: for anonymous tickets we never persist the author.
            user_id=None if anonymous else self.current_user.id,
            category=category,
            message=message,
            anonymous=anonymous,
            status="open",
        )
        self.db.add(ticket)
        await self.db.flush()
        if anonymous:
            # Coarsen created_at to the hour so it can't be cross-referenced with
            # attendance/location/presence timestamps to infer the author.
            ticket.created_at = ticket.created_at.replace(minute=0, second=0, microsecond=0)
            await self.db.flush()
        return ticket

    async def list_for_dashboard(self, category: str | None, status: str | None) -> list[FeedbackTicket]:
        stmt = self.tenant_select(FeedbackTicket).order_by(FeedbackTicket.created_at.desc())
        # RULE 9: harassment/serious categories filtered to Owner at the QUERY level.
        if self.current_user.role != "owner_admin":
            stmt = stmt.where(FeedbackTicket.category.notin_(OWNER_ONLY_CATEGORIES))
        if category is not None:
            if category in OWNER_ONLY_CATEGORIES and self.current_user.role != "owner_admin":
                raise HTTPException(status_code=403, detail="This category is restricted to the company owner")
            stmt = stmt.where(FeedbackTicket.category == category)
        if status is not None:
            stmt = stmt.where(FeedbackTicket.status == status)
        return list((await self.db.execute(stmt)).scalars())

    async def get_one(self, ticket_id: int) -> FeedbackTicket:
        ticket = await self.db.get(FeedbackTicket, ticket_id)
        if ticket is None or ticket.company_id != self.company_id:
            raise HTTPException(status_code=404, detail="Ticket not found")
        if ticket.category in OWNER_ONLY_CATEGORIES and self.current_user.role != "owner_admin":
            raise HTTPException(status_code=404, detail="Ticket not found")  # don't even confirm existence
        return ticket

    async def set_status(self, ticket_id: int, status: str) -> FeedbackTicket:
        ticket = await self.get_one(ticket_id)
        ticket.status = status
        await self.db.flush()
        return ticket

    async def my_tickets(self) -> list[FeedbackTicket]:
        # Only non-anonymous tickets can be listed back to the author —
        # anonymous ones have no author on purpose.
        res = await self.db.execute(
            select(FeedbackTicket).where(FeedbackTicket.user_id == self.current_user.id)
            .order_by(FeedbackTicket.created_at.desc())
        )
        return list(res.scalars())