"""FastAPI dependencies: DB session, current user, role enforcement, plan gating.

Every protected route composes from these. Tenant scoping starts here: company_id
is read from the verified JWT and threaded into services — never from the request body.
"""
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db  # re-exported for convenience
from app.models.company import Subscription
from app.models.users import User

bearer_scheme = HTTPBearer(auto_error=True)

ROLE_OWNER = "owner_admin"
ROLE_MANAGER = "manager"
ROLE_EMPLOYEE = "employee"
ALL_ROLES = (ROLE_OWNER, ROLE_MANAGER, ROLE_EMPLOYEE)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or deactivated")
    # Defense in depth: token tenant must match the user row.
    if user.company_id != payload.get("company_id"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tenant mismatch")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DB = Annotated[AsyncSession, Depends(get_db)]


def require_role(allowed_roles: list[str]):
    """Usage: user: User = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))"""

    async def _dep(user: CurrentUser) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return _dep


# ---------------------------------------------------------------------------
# Plan gating (business rule 8)
# Feature -> minimum tier. Tiers are ordered. Adjust gating tier per feature here.
# ---------------------------------------------------------------------------
PLAN_ORDER = {"startup": 0, "mid": 1, "enterprise": 2}
PLAN_FEATURES: dict[str, str] = {
    "ai_workload_analysis": "mid",
    "ask_your_company": "mid",
    "work_thread_matching": "mid",
    # "goals" removed — available on every plan, including Startup
}


def require_plan_feature(feature_key: str):
    """Blocks the route unless the company's active subscription tier includes the feature."""

    async def _dep(user: CurrentUser, db: DB) -> None:
        min_tier = PLAN_FEATURES.get(feature_key)
        if min_tier is None:  # unknown feature key: fail closed in prod, open in dev? -> fail closed.
            raise HTTPException(status_code=500, detail=f"Unknown plan feature '{feature_key}'")
        res = await db.execute(
            select(Subscription).where(
                Subscription.company_id == user.company_id,
                Subscription.status.in_(("active", "trialing")),
            )
        )
        sub = res.scalar_one_or_none()
        tier = sub.plan_tier if sub else "startup"  # no subscription row => lowest tier
        if PLAN_ORDER.get(tier, 0) < PLAN_ORDER[min_tier]:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Feature '{feature_key}' requires the '{min_tier}' plan or higher",
            )

    return _dep


def require_active_subscription():
    """Blocks all access to a router until the company has a confirmed
    (active/trialing) subscription. Applied at the ROUTER level (see below)
    to every feature router EXCEPT billing.py and auth.py -- otherwise a
    plan-less owner could never reach /billing to actually pay.

    New: checks Company.active FIRST -- a manual platform-admin kill
    switch, completely independent of Stripe/plan status. A company can
    have a perfectly valid paid subscription and still be blocked if
    platform staff have manually deactivated them via the internal admin
    dashboard."""

    async def _dep(user: CurrentUser, db: DB) -> None:
        from app.models.company import Company

        company = await db.get(Company, user.company_id)
        if company is not None and not company.active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This company's access has been suspended. Contact support.",
            )

        res = await db.execute(
            select(Subscription).where(Subscription.company_id == user.company_id)
        )
        sub = res.scalar_one_or_none()
        if sub is None or sub.status not in ("active", "trialing"):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="This company has no active plan. Choose a plan to continue.",
            )

    return _dep

RequireActivePlan = Depends(require_active_subscription())