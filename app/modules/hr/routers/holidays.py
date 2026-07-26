from fastapi import APIRouter, Depends

from app.core.dependencies import DB, ROLE_OWNER, require_role
from app.core.holiday_seed_data import SUPPORTED_COUNTRIES
from app.modules.hr.schemas.holidays import HolidayIn, HolidayOut, HolidaySeedRequest
from app.modules.hr.services.holidays import HolidayService

holidays_router = APIRouter(prefix="/company/holidays", tags=["holidays"])


@holidays_router.get("/countries")
async def list_supported_countries():
    return [{"code": code, "label": label} for code, label in SUPPORTED_COUNTRIES]


@holidays_router.get("", response_model=list[HolidayOut])
async def list_holidays(db: DB, country_code: str | None = None, user=Depends(require_role([ROLE_OWNER]))):
    return await HolidayService(db, user).list_holidays(country_code)


@holidays_router.post("", response_model=HolidayOut, status_code=201)
async def add_holiday(data: HolidayIn, db: DB, user=Depends(require_role([ROLE_OWNER]))):
    return await HolidayService(db, user).add_custom_holiday(data.country_code, data.date, data.name)


@holidays_router.delete("/{holiday_id}", status_code=204)
async def delete_holiday(holiday_id: int, db: DB, user=Depends(require_role([ROLE_OWNER]))):
    await HolidayService(db, user).delete_holiday(holiday_id)
    return None


@holidays_router.post("/seed", response_model=list[HolidayOut], status_code=201)
async def seed_country(data: HolidaySeedRequest, db: DB, user=Depends(require_role([ROLE_OWNER]))):
    """Copies the minimal built-in starter set for a country/year into this
    company's own holidays table. Returns an empty list if everything was
    already seeded (no duplicates created)."""
    return await HolidayService(db, user).seed_country(data.country_code, data.year)