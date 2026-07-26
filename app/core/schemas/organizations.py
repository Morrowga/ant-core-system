from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class CompanyModuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    module_key: str
    status: str
    current_period_end: datetime | None
    auto_renew: bool
    seats_used: int


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    name: str
    industry: str | None
    timezone: str
    currency: str
    working_hours_start: str | None
    working_hours_end: str | None
    workdays: list[str] | None
    created_at: datetime
    modules: list[CompanyModuleOut] = []

    @field_validator("workdays", mode="before")
    @classmethod
    def _split_workdays(cls, value):
        if value is None:
            return None
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [d for d in value.split(",") if d]
        return value


class CompanyCreate(BaseModel):
    name: str
    industry: str | None = None
    timezone: str = "UTC"
    currency: str = "USD"
    working_hours_start: str = "09:00"
    working_hours_end: str = "18:00"
    workdays: list[str] = ["mon", "tue", "wed", "thu", "fri"]


class OrganizationUpdate(BaseModel):
    name: str