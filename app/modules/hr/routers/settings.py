import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select

from app.core.config import settings as app_settings
from app.core.dependencies import (DB, ROLE_MANAGER, ROLE_OWNER, CurrentUser,
                                   require_role, RequireActivePlan)

DashUser = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))
Owner = Depends(require_role([ROLE_OWNER]))

settings_router = APIRouter(prefix="/company/settings", tags=["settings"])
SETTING_SECTIONS = ("profile", "attendance", "reporting", "overtime", "alerts",
                    "health", "knowledge", "feedback", "certificates", "notifications", "invoicing")


def _validate_section(section: str) -> None:
    if section not in SETTING_SECTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown settings section: {section}")

@settings_router.get("/{section}")
async def get_settings(section: str, db: DB, user=Owner):
    _validate_section(section)

    if section == "profile":
        from app.core.models.company import Company
        company = await db.get(Company, user.company_id)
        return {"section": "profile", "data": {
            "name": company.name, "logo_url": company.logo_url,
            "industry": company.industry, "timezone": company.timezone,
            "currency": company.currency,
            "working_hours_start": company.working_hours_start,
            "working_hours_end": company.working_hours_end,
            "working_hours_mode": company.working_hours_mode,
            "workdays": company.workdays,
        }}

    from app.core.models.company import CompanySettings
    row = (await db.execute(select(CompanySettings).where(
        CompanySettings.company_id == user.company_id, CompanySettings.section == section))).scalar_one_or_none()
    return {"section": section, "data": row.data_json if row else {}}


@settings_router.patch("/{section}")
async def patch_settings(section: str, payload: dict, db: DB, user=Owner):
    _validate_section(section)

    if section == "profile":
        from app.core.models.company import Company
        company = await db.get(Company, user.company_id)
        for field in ("name", "logo_url", "industry", "timezone", "currency",
                      "working_hours_start", "working_hours_end", "working_hours_mode", "workdays"):
            if field in payload:
                setattr(company, field, payload[field])
        await db.flush()
        return {"section": "profile", "data": {
            "name": company.name, "logo_url": company.logo_url,
            "industry": company.industry, "timezone": company.timezone,
            "currency": company.currency,
            "working_hours_start": company.working_hours_start,
            "working_hours_end": company.working_hours_end,
            "working_hours_mode": company.working_hours_mode,
            "workdays": company.workdays,
        }}

    from app.core.models.company import CompanySettings
    row = (await db.execute(select(CompanySettings).where(
        CompanySettings.company_id == user.company_id, CompanySettings.section == section))).scalar_one_or_none()
    if row is None:
        row = CompanySettings(company_id=user.company_id, section=section, data_json={})
        db.add(row)
    row.data_json = {**row.data_json, **payload}
    await db.flush()
    return {"section": section, "data": row.data_json}



uploads_router = APIRouter(tags=["uploads"])


@uploads_router.post("/uploads", status_code=201)
async def upload_file(file: UploadFile, user: CurrentUser):
    os.makedirs(app_settings.UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1][:10]
    name = f"{user.company_id}_{uuid.uuid4().hex}{ext}"
    dest = os.path.join(app_settings.UPLOAD_DIR, name)
    size = 0
    with open(dest, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > app_settings.MAX_UPLOAD_MB * 1024 * 1024:
                f.close()
                os.remove(dest)
                raise HTTPException(status_code=413, detail="File too large")
            f.write(chunk)
    return {"url": f"/static/uploads/{name}"}