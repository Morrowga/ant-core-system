from fastapi import APIRouter, Depends

from app.core.dependencies import DB, ROLE_MANAGER, ROLE_OWNER, require_plan_feature, require_role, RequireActivePlan
from app.schemas.misc import AskRequest
from app.services.dashboard import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[RequireActivePlan])
DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))


@router.get("/pulse")
async def pulse(db: DB, user=DashUser):
    return await DashboardService(db, user).pulse()


@router.get("/scorecard")
async def scorecard(db: DB, user=DashUser):
    return await DashboardService(db, user).scorecard()


@router.post("/ask", dependencies=[Depends(require_plan_feature("ask_your_company"))])
async def ask(data: AskRequest, db: DB, user=DashUser):
    """Classify -> deterministic SQL -> narrate. The LLM never computes numbers (rule 3)."""
    return await DashboardService(db, user).ask(data.question)
