from datetime import date

from pydantic import BaseModel, ConfigDict


class HolidayIn(BaseModel):
    country_code: str  # one of the supported codes, or "all" for company-wide
    date: date
    name: str


class HolidayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    country_code: str
    date: date
    name: str
    is_custom: bool


class HolidaySeedRequest(BaseModel):
    country_code: str
    year: int