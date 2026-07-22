from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WaterIn(BaseModel):
    ml: int = Field(gt=0, le=5000)
    prompt_id: int | None = None  # set when answering a specific reminder (see HealthCheckinPrompt)


class MoodIn(BaseModel):
    mood: int = Field(ge=1, le=5)
    prompt_id: int | None = None


class SleepIn(BaseModel):
    hours: float = Field(gt=0, le=24)
    prompt_id: int | None = None


class HealthLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    value: float
    logged_at: datetime


class TeamWellbeingPoint(BaseModel):
    """Aggregated only — never per-user (rule 5)."""

    date: str
    avg_mood: float | None
    avg_water_ml: float | None
    avg_sleep_hours: float | None
    sample_size: int


class HealthCheckinPromptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    sent_at: datetime
    responded_at: datetime | None