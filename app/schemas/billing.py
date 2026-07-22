from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PlanOut(BaseModel):
    tier: str
    name: str
    price_monthly_usd: int
    features: list[str]


class SubscribeRequest(BaseModel):
    plan_tier: str  # startup | mid | enterprise
    payment_method_id: str | None = None


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plan_tier: str
    status: str
    seats_used: int
    renews_at: datetime | None
