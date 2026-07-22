from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: str
    team_id: int | None
    full_name: str | None
    avatar_url: str | None
    joined_at: datetime
    onboarding_completed_at: datetime | None
    active: bool
    timezone: str | None
    holiday_country: str | None
    # New: was missing entirely -- the database updates via the new
    # job-type/actual-working-hours/hourly-fee endpoints were genuinely
    # working, but this response schema never declared these fields, so
    # Pydantic silently dropped them when serializing every response that
    # uses UserOut (including GET /employees and GET /employees/{id}),
    # making the update look like it had no effect at all.
    job_type: str
    actual_working_hours: bool
    hourly_fee: float | None


class UserUpdate(BaseModel):
    full_name: str | None = None
    avatar_url: str | None = None


class EmployeeAdminUpdate(BaseModel):
    full_name: str | None = None
    active: bool | None = None


class RoleUpdate(BaseModel):
    role: str  # owner_admin | manager | employee


class TeamAssign(BaseModel):
    team_id: int | None


class TeamCreate(BaseModel):
    name: str
    manager_id: int | None = None


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    manager_id: int | None


class InviteCreate(BaseModel):
    email: EmailStr
    role: str = "employee"
    team_id: int | None = None
    timezone: str | None = None
    # New: was silently missing entirely -- Pydantic ignores unknown
    # incoming fields rather than erroring, so the frontend has been
    # sending this the whole time with no effect, only surfacing as an
    # AttributeError later when the router tried to read data.holiday_country
    # off a schema that never declared it.
    holiday_country: str | None = None
    # New: invoicing fields, stored on the invite and transferred to the
    # actual User row once accepted.
    job_type: str = "full_time"
    actual_working_hours: bool = True
    hourly_fee: float | None = None


class ConsentIn(BaseModel):
    type: str  # location | health | notifications
    accepted: bool

class TimezoneUpdate(BaseModel):
    timezone: str | None = None

class HolidayCountryUpdate(BaseModel):
    holiday_country: str | None = None

class JobTypeUpdate(BaseModel):
    job_type: str  # full_time | part_time

class ActualWorkingHoursUpdate(BaseModel):
    actual_working_hours: bool

class HourlyFeeUpdate(BaseModel):
    hourly_fee: float | None = None