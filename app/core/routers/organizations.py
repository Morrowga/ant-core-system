"""Organization-level endpoints: list/create Companies under the caller's
Organization, and rename the Organization itself. All three require
owner_admin -- same trust level as registration itself, since these
operations affect billing-relevant structure (a new Company means a new
place modules can be enabled and charged against).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.core.dependencies import DB, ROLE_OWNER, CurrentUser, require_role
from app.core.models.company import Company, Subscription
from app.core.models.company_module import CompanyModule
from app.core.models.organization import Organization
from app.core.schemas.organizations import CompanyCreate, CompanyModuleOut, CompanyOut, OrganizationUpdate

router = APIRouter(tags=["organizations"])
Owner = Depends(require_role([ROLE_OWNER]))


@router.get("/organizations/me", response_model=dict)
async def get_organization(user: CurrentUser, db: DB):
    """Was missing entirely -- the frontend's Organization Settings page
    has nothing to populate its name field from without this. Only
    GET /organizations/{id} equivalent that existed before was the PATCH
    below, which returns the updated row but only on save, never on load.
    """
    organization = await db.get(Organization, user.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return {"id": organization.id, "name": organization.name}


@router.get("/companies", response_model=list[CompanyOut])
async def list_companies(user: CurrentUser, db: DB):
    companies_res = await db.execute(
        select(Company)
        .where(Company.organization_id == user.organization_id)
        .order_by(Company.created_at)
    )
    companies = list(companies_res.scalars())
    if not companies:
        return []

    company_ids = [c.id for c in companies]
    modules_res = await db.execute(
        select(CompanyModule).where(CompanyModule.company_id.in_(company_ids))
    )
    modules_by_company: dict[int, list[CompanyModule]] = {}
    for cm in modules_res.scalars():
        modules_by_company.setdefault(cm.company_id, []).append(cm)

    return [_serialize_company(c, modules_by_company.get(c.id, [])) for c in companies]


@router.post("/organizations/{organization_id}/companies", response_model=CompanyOut, status_code=201)
async def create_company(organization_id: int, data: CompanyCreate, db: DB, user=Owner):
    """Creates a Company under the caller's Organization.

    If the calling owner doesn't have a Company yet (the normal case
    right after registration, now that registration no longer
    auto-creates one -- see auth_service.register_company), this becomes
    THEIR company: user.company_id is set to it, and it gets the same
    Subscription/CompanyModule("hr") stub rows registration used to
    create automatically, so the existing enable-module/billing flow
    works identically regardless of when the Company was created.

    If the owner already has a company (creating an additional one --
    the multi-Company-per-Organization case), user.company_id is left
    alone; the owner stays anchored to their original company and can
    switch context via /companies + whatever "switch active company"
    flow the frontend adds. The new Company still gets its own
    Subscription/CompanyModule stubs so it's immediately usable the
    same way either way.
    """
    if organization_id != user.organization_id:
        raise HTTPException(status_code=403, detail="Not your organization")

    company = Company(
        organization_id=organization_id,
        name=data.name,
        industry=data.industry,
        timezone=data.timezone,
        currency=data.currency,
        working_hours_start=data.working_hours_start,
        working_hours_end=data.working_hours_end,
        workdays=",".join(data.workdays) if data.workdays else "",
    )
    db.add(company)
    await db.flush()

    modules: list[CompanyModule] = []
    db.add(Subscription(company_id=company.id, plan_tier="startup", status="incomplete", seats_used=1))
    hr_module = CompanyModule(company_id=company.id, module_key="hr", status="incomplete", seats_used=1)
    db.add(hr_module)
    modules.append(hr_module)

    if user.company_id is None:
        user.company_id = company.id

    await db.flush()
    return _serialize_company(company, modules)


@router.patch("/organizations/me", response_model=dict)
async def update_organization(data: OrganizationUpdate, db: DB, user=Owner):
    organization = await db.get(Organization, user.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    organization.name = data.name
    await db.flush()
    return {"id": organization.id, "name": organization.name}


def _serialize_company(company: Company, modules: list[CompanyModule]) -> CompanyOut:
    return CompanyOut(
        id=company.id, organization_id=company.organization_id, name=company.name, industry=company.industry,
        timezone=company.timezone, currency=company.currency,
        working_hours_start=company.working_hours_start, working_hours_end=company.working_hours_end,
        workdays=company.workdays, created_at=company.created_at,
        modules=[CompanyModuleOut.model_validate(m) for m in modules],
    )