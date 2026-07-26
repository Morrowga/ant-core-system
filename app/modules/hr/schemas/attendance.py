from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class CheckInRequest(BaseModel):
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)


class LocationPingIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class DeskLocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class AttendanceSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    check_in_at: datetime
    check_out_at: datetime | None
    # These were all being silently stripped from every check-in/check-out
    # response and from GET /attendance/me/status, even though the backend
    # was correctly computing and storing them.
    checked_in_outside_desk: bool = False
    late_minutes: int | None = None
    early_checkout_minutes: int | None = None
    # Not a real database column -- set as a transient attribute on the
    # session object only inside check_in() (see AttendanceService), purely
    # so the mobile app can navigate straight to the sleep question right
    # after check-in without waiting on a push notification tap.
    sleep_prompt_id: int | None = None


class LeaveRequestIn(BaseModel):
    type: str
    start_date: date
    end_date: date
    # Optional time-of-day bounds for partial-day leave (e.g. "2 hours for
    # a bank errand"). Both null = a normal whole-day leave, unchanged
    # behavior. If set, start_date should equal end_date.
    start_time: str | None = None  # "HH:MM"
    end_time: str | None = None


class LeaveRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    type: str
    start_date: date
    end_date: date
    start_time: str | None = None
    end_time: str | None = None
    status: str
    requested_at: datetime


class LeaveStatusUpdate(BaseModel):
    status: str  # approved | rejected