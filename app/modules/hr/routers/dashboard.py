from fastapi import APIRouter, Depends

from app.core.dependencies import DB, ROLE_MANAGER, ROLE_OWNER, require_role, RequireActivePlan
from app.modules.hr.schemas.misc import AskRequest
from app.modules.hr.services.dashboard import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[RequireActivePlan])
DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))


@router.get("/pulse")
async def pulse(db: DB, user=DashUser):
    return await DashboardService(db, user).pulse()


@router.get("/scorecard")
async def scorecard(db: DB, user=DashUser):
    return await DashboardService(db, user).scorecard()


@router.post("/ask")
async def ask(data: AskRequest, db: DB, user=DashUser):
    """Classify -> deterministic SQL -> narrate. The LLM never computes numbers (rule 3)."""
    return await DashboardService(db, user).ask(data.question)