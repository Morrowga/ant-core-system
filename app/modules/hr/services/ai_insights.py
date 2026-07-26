"""AI Insights -- the two summary modes reachable from Overview's "Ask your
company" entry card: a whole-company overview, and a per-project deep dive.

Entirely additive: reuses read-only queries similar in spirit to
dashboard.py/performance.py's own patterns, but doesn't import or modify
either of those services -- kept fully independent so nothing here can
destabilize the existing dashboard pulse/scorecard/ask flow.

Rule 3 still applies to the overview summary (deterministic metrics,
narrated only). The per-project summary is a DELIBERATE, narrow exception
for the "contribution %" figure specifically -- see summarize_project_reports()
in openai_client.py for why, and the hard tone constraints enforced there.
"""
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select

from app.integrations import openai_client
from app.modules.hr.models.attendance import AttendanceSession
from app.modules.hr.models.health import HealthLog
from app.modules.hr.models.reports import Project, Report
from app.core.models.user import Team, User
from app.core.services.base import TenantService

PROJECT_ANALYSIS_COOLDOWN = timedelta(hours=1)
MIN_HEALTH_CONTRIBUTORS = 3  # same privacy floor used elsewhere -- never show below this
EXTREME_LATE_THRESHOLD_MINUTES = 120  # beyond this, treat as an unauthorized absence, not "late"


def _format_money(amount: float, currency: str) -> str:
    symbols = {"USD": "$", "JPY": "¥", "EUR": "€", "GBP": "£", "VND": "₫", "THB": "฿", "INR": "₹"}
    symbol = symbols.get(currency)
    if symbol:
        # No decimals for zero-decimal currencies (JPY, VND, KRW) -- showing
        # "¥2,000,000.00" looks wrong for currencies that don't use cents.
        if currency in ("JPY", "VND", "KRW"):
            return f"{symbol}{amount:,.0f}"
        return f"{symbol}{amount:,.2f}"
    return f"{amount:,.2f} {currency}"


def _assert_period_excludes_today(end: date) -> None:
    """New: reports only land at checkout, so "today" is always incomplete
    while shifts are still in progress. Both summary modes are restricted
    to fully-completed days only -- this isn't a limitation to apologize
    for, it's what keeps the numbers honest."""
    if end >= date.today():
        raise HTTPException(
            status_code=400,
            detail="Choose a period that ends yesterday or earlier -- today's data is still incomplete until shifts end.",
        )


class AIInsightsService(TenantService):
    # ================================================================ overview
    async def _is_holiday(self, holiday_country: str | None, day: date, holidays_cache: dict) -> bool:
        """Cached per (country, day) within one call to avoid re-querying
        for every session/day across potentially many employees."""
        from app.core.models.company import Holiday

        key = (holiday_country, day)
        if key in holidays_cache:
            return holidays_cache[key]
        conditions = [Holiday.date == day, Holiday.company_id == self.company_id]
        if holiday_country:
            row = (await self.db.execute(
                select(Holiday).where(
                    Holiday.company_id == self.company_id, Holiday.date == day,
                    (Holiday.country_code == holiday_country) | (Holiday.country_code == "all"),
                ).limit(1)
            )).scalar_one_or_none()
        else:
            row = (await self.db.execute(
                select(Holiday).where(
                    Holiday.company_id == self.company_id, Holiday.date == day, Holiday.country_code == "all",
                ).limit(1)
            )).scalar_one_or_none()
        is_holiday = row is not None
        holidays_cache[key] = is_holiday
        return is_holiday

    async def _late_minutes_by_team(self, start: date, end: date, holidays_cache: dict) -> list[dict]:
        """Total late-arrival minutes, grouped by team. Excludes: holidays
        (this employee's own country, or company-wide), and any session
        where late_minutes exceeds EXTREME_LATE_THRESHOLD_MINUTES -- that
        gets reclassified as an unauthorized absence instead (see
        _unauthorized_absences()), not counted as "late" here."""
        rows = (await self.db.execute(
            select(AttendanceSession.check_in_at, AttendanceSession.late_minutes,
                  Team.name, User.holiday_country)
            .select_from(AttendanceSession)
            .join(User, User.id == AttendanceSession.user_id)
            .outerjoin(Team, Team.id == User.team_id)
            .where(
                User.company_id == self.company_id,
                AttendanceSession.late_minutes.is_not(None),
                func.date(AttendanceSession.check_in_at) >= start,
                func.date(AttendanceSession.check_in_at) <= end,
            )
        )).all()

        totals: dict[str, int] = {}
        for check_in_at, late_minutes, team_name, holiday_country in rows:
            if late_minutes is None or late_minutes <= 0:
                continue
            if late_minutes > EXTREME_LATE_THRESHOLD_MINUTES:
                continue  # counted as an unauthorized absence instead
            day = check_in_at.date()
            if await self._is_holiday(holiday_country, day, holidays_cache):
                continue
            key = team_name or "Unassigned"
            totals[key] = totals.get(key, 0) + int(late_minutes)

        return [{"team": team, "total_late_minutes": total} for team, total in totals.items()]

    async def list_unauthorized_absences(self, start: date, end: date) -> list[dict]:
        """Public entry point -- same logic _unauthorized_absences() uses
        inside generate_overview(), but manages its own holidays_cache so
        it can be called standalone (e.g. from the Attendance page's
        Absent tab, which isn't part of the AI-generated overview and
        shouldn't require the Mid-tier plan gate that route sits behind).

        New: today IS now allowed (previously hard-rejected). Today is
        handled as a LIVE, progressively-filling view rather than a fixed
        historical judgment -- see _unauthorized_absences() for exactly how
        each job_type is evaluated as of the current moment."""
        if end > date.today():
            raise HTTPException(status_code=400, detail="period_end can't be in the future")
        return await self._unauthorized_absences(start, end, {})

    async def _unauthorized_absences(self, start: date, end: date, holidays_cache: dict) -> list[dict]:
        """Anyone who, on a scheduled workday, either has no attendance
        session at all OR checked in more than EXTREME_LATE_THRESHOLD_MINUTES
        late -- UNLESS an approved leave request covers that day, in which
        case it's legitimate leave, not an unauthorized absence. Holidays
        and weekends are never flagged.

        New: TODAY is evaluated live, as of right now, differently per
        job_type:
          - full_time: if their shift hasn't started yet (now < shift
            start), they're skipped entirely for today -- can't be absent
            from a shift that hasn't begun. Once the shift has started,
            the same 2-hour-late threshold applies, just computed against
            "now" instead of end-of-day.
          - part_time: no shift-time concept at all (flexible hours by
            design) -- simply checked for whether they have ANY session
            recorded today yet, no time-of-day comparison.
        Every day before today keeps the exact same logic as before,
        completely unchanged."""
        from app.modules.hr.models.attendance import LeaveRequest
        from app.core.models.company import Company
        from app.core.worktime import compute_shift_bounds_utc

        company = await self.db.get(Company, self.company_id)
        workday_codes = {d.strip() for d in (company.workdays or "").split(",") if d.strip()}
        weekday_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        today = date.today()
        now = datetime.now(timezone.utc)

        users = list((await self.db.execute(
            select(User).where(User.company_id == self.company_id, User.active.is_(True))
        )).scalars())

        sessions_by_user_day: dict[tuple[int, date], int | None] = {}
        rows = (await self.db.execute(
            select(AttendanceSession.user_id, AttendanceSession.check_in_at, AttendanceSession.late_minutes)
            .join(User, User.id == AttendanceSession.user_id)
            .where(User.company_id == self.company_id,
                  func.date(AttendanceSession.check_in_at) >= start,
                  func.date(AttendanceSession.check_in_at) <= end)
        )).all()
        for user_id, check_in_at, late_minutes in rows:
            sessions_by_user_day[(user_id, check_in_at.date())] = late_minutes

        leave_rows = (await self.db.execute(
            select(LeaveRequest.user_id, LeaveRequest.start_date, LeaveRequest.end_date)
            .join(User, User.id == LeaveRequest.user_id)
            .where(User.company_id == self.company_id, LeaveRequest.status == "approved",
                  LeaveRequest.start_date <= end, LeaveRequest.end_date >= start)
        )).all()
        leave_days: dict[int, set[date]] = {}
        for user_id, leave_start, leave_end in leave_rows:
            days = leave_days.setdefault(user_id, set())
            d = max(leave_start, start)
            while d <= min(leave_end, end):
                days.add(d)
                d += timedelta(days=1)

        out = []
        for user in users:
            d = start
            while d <= end:
                if weekday_names[d.weekday()] in workday_codes:
                    if d in leave_days.get(user.id, set()):
                        d += timedelta(days=1)
                        continue
                    if await self._is_holiday(user.holiday_country, d, holidays_cache):
                        d += timedelta(days=1)
                        continue

                    late_minutes = sessions_by_user_day.get((user.id, d), "no_session")
                    is_part_time = getattr(user, "job_type", "full_time") == "part_time"

                    if d == today:
                        if is_part_time:
                            # Simple check only -- no shift-time concept for
                            # flexible hours. Do they have a session yet today?
                            if late_minutes == "no_session":
                                out.append({"employee_name": user.full_name, "date": str(d)})
                        else:
                            try:
                                employee_tz = getattr(user, "timezone", None) or company.timezone
                                shift_start_utc, _ = compute_shift_bounds_utc(
                                    company.working_hours_start, company.working_hours_end,
                                    company.timezone, employee_tz, company.working_hours_mode,
                                )
                            except Exception:
                                shift_start_utc = None
                            if shift_start_utc is not None and now < shift_start_utc:
                                pass  # shift hasn't started yet -- can't be absent from it
                            elif late_minutes == "no_session":
                                if shift_start_utc is not None and (now - shift_start_utc).total_seconds() / 60 > EXTREME_LATE_THRESHOLD_MINUTES:
                                    out.append({"employee_name": user.full_name, "date": str(d)})
                                # else: still within the grace window as of right now, not flagged yet
                            elif isinstance(late_minutes, int) and late_minutes > EXTREME_LATE_THRESHOLD_MINUTES:
                                out.append({"employee_name": user.full_name, "date": str(d)})
                    else:
                        # Unchanged historical logic for every day before today.
                        if late_minutes == "no_session" or (isinstance(late_minutes, int) and late_minutes > EXTREME_LATE_THRESHOLD_MINUTES):
                            out.append({"employee_name": user.full_name, "date": str(d)})
                d += timedelta(days=1)
        return out

    async def _health_summary(self, start: date, end: date) -> dict:
        """Team-wide averages only, same privacy floor as everywhere else
        in this app -- never broken down by individual."""
        start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)

        async def avg_for(health_type: str) -> dict:
            row = (await self.db.execute(
                select(func.avg(HealthLog.value), func.count(func.distinct(HealthLog.user_id)))
                .join(User, User.id == HealthLog.user_id)
                .where(User.company_id == self.company_id, HealthLog.type == health_type,
                       HealthLog.logged_at >= start_dt, HealthLog.logged_at <= end_dt)
            )).one()
            avg_value, contributors = row[0], row[1] or 0
            if contributors < MIN_HEALTH_CONTRIBUTORS:
                return {"average": None, "note": "Not enough contributors to show a group average"}
            return {"average": round(float(avg_value), 2), "contributors": contributors}

        return {
            "mood": await avg_for("mood"),
            "water_ml": await avg_for("water"),
            "sleep_hours": await avg_for("sleep"),
        }

    async def _projects_overview(self, start: date, end: date, currency: str) -> list[dict]:
        projects = list((await self.db.execute(
            select(Project).where(Project.company_id == self.company_id, Project.active.is_(True))
        )).scalars())
        out = []
        for project in projects:
            hours = float(await self.db.scalar(
                select(func.coalesce(func.sum(Report.hours), 0)).where(
                    Report.project_id == project.id, Report.report_date >= start, Report.report_date <= end,
                )
            ) or 0)
            # New: format as a currency string using the COMPANY'S actual
            # currency, not a bare number -- narrate() has no other way to
            # know what currency this is, and was defaulting to "$" (USD)
            # since that's the most common symbol in its training data,
            # not because it was ever told this company uses JPY (or
            # anything else). Passing an already-formatted string removes
            # any guessing.
            deal_price_display = None
            if project.deal_price is not None:
                try:
                    deal_price_display = _format_money(project.deal_price, currency)
                except Exception:
                    deal_price_display = f"{project.deal_price} {currency}"
            out.append({
                "name": project.name, "hours_logged_in_period": round(hours, 1),
                "deal_price_display": deal_price_display, "deadline": str(project.estimated_end_date) if project.estimated_end_date else None,
                "completed": project.completed_at is not None,
            })
        return out

    async def generate_overview(self, start: date, end: date) -> dict:
        if end > date.today():
            raise HTTPException(status_code=400, detail="period_end can't be in the future")

        from app.modules.hr.models.attendance import LeaveRequest  # local import, mirrors dashboard.py's own style
        from app.core.models.company import Company

        company = await self.db.get(Company, self.company_id)
        currency = getattr(company, "currency", None) or "USD"

        active_ids = [r for (r,) in (await self.db.execute(
            select(User.id).where(User.company_id == self.company_id, User.active.is_(True))
        )).all()]

        on_leave_today = set()
        if active_ids:
            rows = await self.db.execute(
                select(LeaveRequest.user_id).where(
                    LeaveRequest.user_id.in_(active_ids), LeaveRequest.status == "approved",
                    LeaveRequest.start_date <= date.today(), LeaveRequest.end_date >= date.today(),
                )
            )
            on_leave_today = {r for (r,) in rows.all()}
        expected = set(active_ids) - on_leave_today

        checked_in_count = 0
        if expected:
            start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
            end_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
            checked_in_count = await self.db.scalar(
                select(func.count(func.distinct(AttendanceSession.user_id))).where(
                    AttendanceSession.user_id.in_(expected),
                    AttendanceSession.check_in_at >= start_dt, AttendanceSession.check_in_at <= end_dt,
                )
            ) or 0
        attendance_pct = round(checked_in_count / len(expected) * 100, 1) if expected else 0.0

        # Shared across both calls so a (country, day) holiday lookup is
        # never repeated -- both methods check holiday status per employee/day.
        holidays_cache: dict = {}

        # New: today is now allowed, but report-dependent data (project
        # hours) can't be trusted yet if today is included -- reports only
        # land at checkout, so mid-shift the real numbers simply don't
        # exist. Rather than silently show an incomplete/misleading
        # projects section, it's explicitly omitted with a note when
        # today's in the range; attendance/absences/health are still shown
        # live since those don't depend on end-of-shift reporting at all.
        includes_today = end == date.today()
        projects = None if includes_today else await self._projects_overview(start, end, currency)

        metrics = {
            "period_start": str(start), "period_end": str(end),
            "currency": currency,
            "includes_today": includes_today,
            "attendance_pct": attendance_pct,
            "late_minutes_by_team": await self._late_minutes_by_team(start, end, holidays_cache),
            "unauthorized_absences": await self._unauthorized_absences(start, end, holidays_cache),
            "health": await self._health_summary(start, end),
            "projects": projects,
            "projects_note": (
                "Not available yet -- today's shifts haven't all ended, so report data is still incomplete."
                if includes_today else None
            ),
        }

        narrative = openai_client.narrate({"metric": "company_overview", **metrics})

        from app.modules.hr.models.ai_insights import CompanyOverviewAnalysis
        row = CompanyOverviewAnalysis(
            company_id=self.company_id, period_start=start, period_end=end,
            metrics_json=metrics, narrative_text=narrative,
        )
        self.db.add(row)
        await self.db.flush()

        return {"metrics": metrics, "narrative": narrative, "generated_at": row.generated_at}

    # ================================================================ per-project
    async def _latest_project_analysis(self, project_id: int):
        from app.modules.hr.models.ai_insights import ProjectAnalysis
        return (await self.db.execute(
            select(ProjectAnalysis).where(ProjectAnalysis.project_id == project_id)
            .order_by(ProjectAnalysis.generated_at.desc()).limit(1)
        )).scalar_one_or_none()

    async def project_cooldown_status(self, project_id: int) -> dict:
        """Lets the frontend check before attempting generation, so it can
        show "come back at HH:MM" without a wasted round trip."""
        latest = await self._latest_project_analysis(project_id)
        if latest is None:
            return {"on_cooldown": False, "can_generate_at": None, "latest": None}
        generated_at = latest.generated_at if latest.generated_at.tzinfo else latest.generated_at.replace(tzinfo=timezone.utc)
        can_generate_at = generated_at + PROJECT_ANALYSIS_COOLDOWN
        now = datetime.now(timezone.utc)
        return {
            "on_cooldown": now < can_generate_at,
            "can_generate_at": can_generate_at,
            "latest": {
                "metrics": latest.metrics_json, "narrative": latest.narrative_text,
                "generated_at": latest.generated_at, "period_start": str(latest.period_start),
                "period_end": str(latest.period_end),
            },
        }

    async def generate_project_analysis(self, project_id: int, start: date, end: date) -> dict:
        _assert_period_excludes_today(end)

        from app.core.models.company import Company

        project = await self.db.get(Project, project_id)
        if project is None or project.company_id != self.company_id:
            raise HTTPException(status_code=404, detail="Project not found")

        company = await self.db.get(Company, self.company_id)
        currency = getattr(company, "currency", None) or "USD"

        cooldown = await self.project_cooldown_status(project_id)
        if cooldown["on_cooldown"]:
            # Return the cached result rather than erroring -- the
            # frontend shows this as "here's the latest, come back after
            # <can_generate_at> to refresh" rather than a dead end.
            return {**cooldown["latest"], "cached": True, "can_regenerate_at": cooldown["can_generate_at"]}

        rows = (await self.db.execute(
            select(User.id, User.full_name, Report.hours, Report.summary)
            .join(User, User.id == Report.user_id)
            .where(Report.project_id == project_id, Report.report_date >= start, Report.report_date <= end)
            .order_by(User.id, Report.report_date)
        )).all()

        by_employee: dict[int, dict] = {}
        total_hours = 0.0
        for user_id, full_name, hours, summary in rows:
            entry = by_employee.setdefault(user_id, {"name": full_name, "hours": 0.0, "report_summaries": []})
            entry["hours"] += float(hours)
            entry["report_summaries"].append(summary)
            total_hours += float(hours)

        employees = []
        for entry in by_employee.values():
            hours_share_pct = round(entry["hours"] / total_hours * 100, 1) if total_hours > 0 else 0.0
            employees.append({
                "name": entry["name"], "hours": round(entry["hours"], 1),
                "hours_share_pct": hours_share_pct, "report_summaries": entry["report_summaries"],
            })

        # Same fix as the overview summary -- pass an already-formatted
        # currency string, not a bare number, so the model can't guess a
        # currency symbol it was never told.
        deal_price_display = _format_money(project.deal_price, currency) if project.deal_price is not None else None

        precomputed = {
            "project_name": project.name, "deal_price_display": deal_price_display,
            "deadline": str(project.estimated_end_date) if project.estimated_end_date else None,
            "period_start": str(start), "period_end": str(end),
            "employees": employees,
        }

        ai_result = openai_client.summarize_project_reports(precomputed)

        metrics = {
            **precomputed,
            "total_hours": round(total_hours, 1),
            "summary_bullets": ai_result["summary_bullets"],
            "contributions": ai_result["contributions"],
        }
        # Narrative here is just a short intro line; the bullets/contributions
        # ARE the actual content, shown directly by the frontend rather than
        # folded into one big narrated paragraph.
        narrative = (
            f"{project.name}: {round(total_hours, 1)}h logged across {len(employees)} "
            f"employee{'s' if len(employees) != 1 else ''} between {start} and {end}."
        )

        from app.modules.hr.models.ai_insights import ProjectAnalysis
        row = ProjectAnalysis(
            company_id=self.company_id, project_id=project_id, period_start=start, period_end=end,
            metrics_json=metrics, narrative_text=narrative,
        )
        self.db.add(row)
        await self.db.flush()

        return {
            "metrics": metrics, "narrative": narrative, "generated_at": row.generated_at,
            "period_start": str(start), "period_end": str(end), "cached": False, "can_regenerate_at": None,
        }