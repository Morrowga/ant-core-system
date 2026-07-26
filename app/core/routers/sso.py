"""SSO handoff endpoints between Core Dashboard and every module frontend.

POST /auth/sso/issue-code -- called by Core Dashboard once a logged-in
user clicks "Enter" on an enabled module. Requires the caller to already
be authenticated (that's the whole point: we're vouching for someone
who's already logged in here). Returns a random, single-use code valid
for ~30 seconds.

POST /auth/sso/consume -- called by the target module's frontend
(HR Dashboard, Warehouse, POS, ...) on load, if a ?code= is present in
the URL. Deliberately public/unauthenticated: the person arriving here
hasn't logged into THIS frontend yet, that's exactly what this call
does for them. Trust comes entirely from the code being valid, unused,
and unexpired -- not from any token this request could carry.
"""
from fastapi import APIRouter

from app.core.dependencies import DB, CurrentUser
from app.core.schemas.auth import TokenPair
from app.core.schemas.sso import ConsumeCodeRequest, IssueCodeResponse
from app.core.services import sso as sso_service

router = APIRouter(prefix="/auth/sso", tags=["sso"])


@router.post("/issue-code", response_model=IssueCodeResponse)
async def issue_code(user: CurrentUser, db: DB):
    code, expires_in = await sso_service.issue_code(db, user)
    return IssueCodeResponse(code=code, expires_in=expires_in)


@router.post("/consume", response_model=TokenPair)
async def consume_code(data: ConsumeCodeRequest, db: DB):
    return await sso_service.consume_code(db, data.code)