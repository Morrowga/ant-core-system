from fastapi import APIRouter, Depends

from app.core.dependencies import DB, ROLE_MANAGER, ROLE_OWNER, CurrentUser, require_role, RequireActivePlan
from app.modules.hr.schemas.misc import FeedbackIn, FeedbackOut
from app.modules.hr.services.feedback import FeedbackService

router = APIRouter(prefix="/feedback", tags=["feedback"], dependencies=[RequireActivePlan])
DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))


@router.post("", response_model=FeedbackOut, status_code=201)
async def create_feedback(data: FeedbackIn, user: CurrentUser, db: DB):
    """Anonymous tickets never store the author and get hour-coarsened timestamps (rule 10)."""
    return await FeedbackService(db, user).create(data.category, data.message, data.anonymous)


@router.get("/me", response_model=list[FeedbackOut])
async def my_feedback(user: CurrentUser, db: DB):
    return await FeedbackService(db, user).my_tickets()


@router.get("", response_model=list[FeedbackOut])
async def list_feedback(db: DB, category: str | None = None, status: str | None = None, user=DashUser):
    """Harassment category auto-filtered to Owner at the query level (rule 9)."""
    return await FeedbackService(db, user).list_for_dashboard(category, status)


@router.get("/{ticket_id}", response_model=FeedbackOut)
async def get_feedback(ticket_id: int, db: DB, user=DashUser):
    return await FeedbackService(db, user).get_one(ticket_id)


@router.patch("/{ticket_id}/status", response_model=FeedbackOut)
async def set_status(ticket_id: int, payload: dict, db: DB, user=DashUser):
    return await FeedbackService(db, user).set_status(ticket_id, payload.get("status", "open"))
