from datetime import date as date_type

from fastapi import HTTPException
from sqlalchemy import select

from app.core.holiday_seed_data import BUILTIN_HOLIDAYS
from app.models.company import Holiday
from app.services.base import TenantService


class HolidayService(TenantService):
    async def list_holidays(self, country_code: str | None = None) -> list[Holiday]:
        stmt = self.tenant_select(Holiday).order_by(Holiday.date)
        if country_code is not None:
            stmt = stmt.where((Holiday.country_code == country_code) | (Holiday.country_code == "all"))
        return list((await self.db.execute(stmt)).scalars())

    async def add_custom_holiday(self, country_code: str, holiday_date: date_type, name: str) -> Holiday:
        h = Holiday(company_id=self.current_user.company_id, country_code=country_code,
                    date=holiday_date, name=name, is_custom=True)
        self.db.add(h)
        await self.db.flush()
        return h

    async def delete_holiday(self, holiday_id: int) -> None:
        h = await self.db.get(Holiday, holiday_id)
        if h is None or h.company_id != self.current_user.company_id:
            raise HTTPException(status_code=404, detail="Holiday not found")
        await self.db.delete(h)

    async def seed_country(self, country_code: str, year: int) -> list[Holiday]:
        """Copies the built-in starter set for a country/year into this
        company's own Holiday table -- after this, rows are fully
        owner-editable/deletable, no different from a manually-added
        custom entry. Deliberately minimal seed data (see
        holiday_seed_data.py) -- most real dates still need to be added
        manually by the owner from a source they trust."""
        year_data = BUILTIN_HOLIDAYS.get(year, {})
        entries = year_data.get(country_code, [])
        if not entries:
            raise HTTPException(
                status_code=404,
                detail=f"No built-in starter data for {country_code} in {year} -- add holidays manually instead.",
            )
        created = []
        for entry in entries:
            # Seed data stores dates as "YYYY-MM-DD" strings -- Postgres's
            # DATE column can't be compared against a raw string without an
            # explicit cast, so parse it into a real date object first.
            entry_date = date_type.fromisoformat(entry["date"])
            existing = (await self.db.execute(
                select(Holiday).where(
                    Holiday.company_id == self.current_user.company_id,
                    Holiday.country_code == country_code,
                    Holiday.date == entry_date,
                )
            )).scalar_one_or_none()
            if existing is not None:
                continue
            h = Holiday(company_id=self.current_user.company_id, country_code=country_code,
                        date=entry_date, name=entry["name"], is_custom=False)
            self.db.add(h)
            created.append(h)
        await self.db.flush()
        return created

    async def is_holiday_today(self, holiday_country: str | None) -> bool:
        """Used by AttendanceService.check_in() and the health reminder
        task. `holiday_country` is the EMPLOYEE's own assigned country
        (User.holiday_country) -- if they don't have one set, this always
        returns False (no country assigned = no holiday blocking for them)."""
        if holiday_country is None:
            return False
        today = date_type.today()
        stmt = select(Holiday).where(
            Holiday.company_id == self.current_user.company_id,
            Holiday.date == today,
            (Holiday.country_code == holiday_country) | (Holiday.country_code == "all"),
        ).limit(1)
        return (await self.db.execute(stmt)).scalar_one_or_none() is not None