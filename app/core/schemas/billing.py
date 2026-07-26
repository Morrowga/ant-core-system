from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ModuleOut(BaseModel):
    """One catalog entry -- what a module costs, flat, no tiers."""
    module_key: str
    name: str
    price_monthly_usd: int
    description: str


class EnableModuleRequest(BaseModel):
    payment_method_id: str | None = None


class CompanyModuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    module_key: str
    status: str
    seats_used: int
    current_period_end: datetime | None
    auto_renew: bool
    renews_at: datetime | None