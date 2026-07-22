from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FeedbackIn(BaseModel):
    category: str
    message: str = Field(min_length=1)
    anonymous: bool = False


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: str
    message: str
    anonymous: bool
    status: str
    created_at: datetime
    # user_id intentionally excluded from the default out-schema; owner views use a
    # dedicated serializer that only reveals user_id for NON-anonymous tickets.


class RecognitionIn(BaseModel):
    employee_id: int
    report_id: int | None = None
    reason: str = Field(min_length=1)


class KnowledgePostIn(BaseModel):
    title: str
    body: str
    category: str | None = None
    must_acknowledge: bool = False
    ack_deadline_days: int | None = None


class DeviceRegisterIn(BaseModel):
    fcm_token: str
    # New: "dashboard" added -- the Owner/Manager dashboard registers under
    # this distinct value so notification_service.send()'s audience="dashboard"
    # routing can target it exclusively, separate from "mobile" and "web"
    # (the employee portal). Previously this pattern rejected "dashboard"
    # outright with a 422, silently breaking dashboard push registration.
    platform: str = Field(pattern="^(mobile|web|dashboard)$")


class HeartbeatIn(BaseModel):
    platform: str = Field(pattern="^(mobile|web|dashboard)$")
    app_state: str = "foreground"


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)