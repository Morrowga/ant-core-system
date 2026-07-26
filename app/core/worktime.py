"""Shift-time math shared by attendance status, late detection, and the
home screen countdown. Two modes (set per-company in Settings):

  "company_timezone" -- working_hours_start/end are ONE fixed instant in
    the company's own timezone. Every employee's local clock shows a
    DIFFERENT wall-clock number for that same instant, depending on their
    own offset from the company (e.g. company 8:30 JST -> an employee in
    Vietnam, 2h behind, sees their own clock read 6:00 AM at that moment).

  "local_wall_clock" -- working_hours_start/end are a literal wall-clock
    pattern applied identically in EVERY employee's own timezone, with no
    real UTC conversion between company and employee at all (company sets
    8:30 JST -> an employee in Vietnam also starts at 8:30 AM their own
    Vietnam-local time).

Known simplification: assumes a same-day shift (end time is later than
start time on the same calendar day) -- overnight shifts crossing midnight
aren't handled here yet.
"""
from datetime import date, datetime, time as dt_time
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo


def _parse_hhmm(value: str) -> dt_time:
    hour, minute = value.split(":")
    return dt_time(int(hour), int(minute))


def compute_shift_bounds_utc(
    working_hours_start: str,
    working_hours_end: str,
    company_timezone: str,
    employee_timezone: str | None,
    mode: str,
    *,
    on_date: date | None = None,
) -> tuple[datetime, datetime]:
    """Returns (shift_start_utc, shift_end_utc) as timezone-aware UTC
    datetimes for a given calendar day (defaults to "today" in whichever
    timezone the mode anchors to), per the company's working_hours_mode."""
    start_t = _parse_hhmm(working_hours_start)
    end_t = _parse_hhmm(working_hours_end)

    # Which timezone the wall-clock numbers are anchored to depends on the
    # mode -- this one line IS the entire difference between the two modes.
    anchor_tz_name = company_timezone if mode == "company_timezone" else (employee_timezone or company_timezone)
    anchor_tz = ZoneInfo(anchor_tz_name)

    day = on_date if on_date is not None else datetime.now(anchor_tz).date()

    start_local = datetime.combine(day, start_t, tzinfo=anchor_tz)
    end_local = datetime.combine(day, end_t, tzinfo=anchor_tz)

    return start_local.astimezone(dt_timezone.utc), end_local.astimezone(dt_timezone.utc)