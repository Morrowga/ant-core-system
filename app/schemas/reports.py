from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ReportEntryIn(BaseModel):
    project_id: int | None = None
    hours: float = Field(gt=0, le=24)
    summary: str = Field(min_length=1)


class ReportUpdate(BaseModel):
    project_id: int | None = None
    hours: float | None = Field(None, gt=0, le=24)
    summary: str | None = None


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    project_id: int | None
    hours: float
    summary: str
    report_date: date
    editable_until: datetime
    created_at: datetime


class ReportCommentIn(BaseModel):
    comment: str = Field(min_length=1)


class ProjectIn(BaseModel):
    name: str
    description: str | None = None
    # New: financials, all optional at creation -- can be set later via
    # PATCH once the deal terms are actually known.
    deal_price: float | None = None
    estimated_start_date: date | None = None
    estimated_end_date: date | None = None
    # New: which employees can pick this project when submitting a report.
    # Owner/Manager can still see/manage every project regardless.
    employee_ids: list[int] | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    active: bool
    deal_price: float | None
    estimated_start_date: date | None
    estimated_end_date: date | None
    completed_at: datetime | None

class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    active: bool | None = None
    deal_price: float | None = None
    estimated_start_date: date | None = None
    estimated_end_date: date | None = None
    completed_at: datetime | None = None
    # New: replaces the full assigned-employee list when provided (not a
    # merge) -- matches how the dashboard form works: pick the full set,
    # save. Omit the field entirely to leave assignments untouched.
    employee_ids: list[int] | None = None


class ProjectAssignmentOut(BaseModel):
    user_id: int
    full_name: str | None
    email: str


class ProjectExpenseIn(BaseModel):
    description: str = Field(min_length=1)
    amount: float = Field(gt=0)


class ProjectExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    description: str
    amount: float
    added_by: int | None
    created_at: datetime


# ---------- overtime: request + approve, then start/end ----------

class OvertimeRequestIn(BaseModel):
    requested_date: date
    planned_start_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    planned_end_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    reason: str = Field(min_length=1)


class OvertimeRequestDecision(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")


class OvertimeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    requested_date: date
    planned_start_time: str
    planned_end_time: str
    reason: str
    status: str
    decided_by: int | None
    decided_at: datetime | None
    created_at: datetime


class OvertimeStart(BaseModel):
    # project_id is still optional at start time; reason/timing now come
    # from the approved OvertimeRequest for today, not typed fresh here.
    project_id: int | None = None


class OvertimeReportIn(BaseModel):
    summary: str = Field(min_length=1)


class OvertimeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    project_id: int | None
    initiated_by: str
    reason: str | None
    request_id: int | None
    start_at: datetime
    end_at: datetime | None
    hours: float | None
    summary: str | None
    ai_summary: str | None