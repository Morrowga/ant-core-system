"""Performance metrics — ALL deterministic SQL/arithmetic (rule 3).

The LLM is never involved here. Pace labels are read from ai_workload_analysis
rows that were classified earlier per-report; everything else is plain SQL.

New: every hours figure (daily list, Impact Score's hours_logged/team_avg,
Team Comparison) now ALSO includes completed OvertimeSession.hours
(end_at set, meaning a closing summary was required and hours were
computed), attributed to the local date the session started on. Pace
distribution stays Report-only, since overtime summaries never go through
AI analysis. Overtime hours were previously invisible to this entire
module.

Impact Score — documented weighting (tune the constants below):

    hours_score      = min(hours / team_avg_hours, 1.5) / 1.5 * 100
                       (100 = 1.5x the team average; capped so nobody "wins" by
                        logging absurd hours; if no team average, score 50)
    pace_score       = 100 * (steady*1.00 + heavy*0.90 + unclear*0.75 + light*0.50)
                       (steady is the ideal; heavy slightly discounted to avoid
                        rewarding chronic overwork; weights sum against the
                        label distribution which itself sums to 1.0)
    base             = 0.6 * hours_score + 0.4 * pace_score
    recognition_bonus= 1 + 0.02 * min(recognitions, 5)      (max +10%)
    attendance_mult  = attendance_reliability_pct / 100
    impact_score     = round(clamp(base * recognition_bonus * attendance_mult, 0, 100))

Attendance reliability — documented definition:
    scheduled days   = weekdays (Mon-Fri) between max(period start, join date)
                       and today, excluding days covered by an approved leave
    on-time          = AttendanceSession.late_minutes is null or <= GRACE_MINUTES,
                       where late_minutes was computed at check-in time via
                       compute_shift_bounds_utc() (full per-employee timezone +
                       company working_hours_mode awareness -- see
                       AttendanceService.check_in())
    reliability_pct  = on-time days / scheduled days * 100 (100 if none scheduled)
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select

from app.modules.hr.models.attendance import AttendanceSession, LeaveRequest
from app.core.models.company import Company
from app.modules.hr.models.misc import AIWorkloadAnalysis, Recognition
from app.modules.hr.models.reports import OvertimeSession, Report
from app.core.models.user import Team, User
from app.core.services.base import TenantService

GRACE_MINUTES = 15
PACE_WEIGHTS = {"steady": 1.00, "heavy": 0.90, "unclear": 0.75, "light": 0.50}
HOURS_WEIGHT, PACE_WEIGHT = 0.6, 0.4
RECOGNITION_BONUS_PER = 0.02  # per recognition, capped at 5


class PerformanceService(TenantService):
    async def _target(self, employee_id: int) -> User:
        target = await self.assert_user_in_tenant(employee_id)
        if not self.can_view_employee(target):
            raise HTTPException(status_code=403, detail="Not allowed for this employee")
        return target

    async def _company(self) -> Company:
        return await self.db.get(Company, self.company_id)

    # ------------------------------------------------------------------ helpers
    async def daily_overtime_hours(self, user_id: int, start: date, end: date) -> dict[date, float]:
        """New: completed overtime sessions (end_at set -- meaning a
        closing summary was required and hours were actually computed),
        attributed to the LOCAL DATE they started on. Overtime workload now
        counts toward performance the same way regular reported hours do --
        previously invisible to this whole module entirely."""
        rows = await self.db.execute(
            select(OvertimeSession.start_at, OvertimeSession.hours)
            .where(OvertimeSession.user_id == user_id, OvertimeSession.end_at.is_not(None),
                   OvertimeSession.hours.is_not(None))
        )
        out: dict[date, float] = {}
        for start_at, hours in rows.all():
            day = start_at.date()
            if start <= day <= end:
                out[day] = out.get(day, 0.0) + float(hours)
        return out

    async def daily_hours(self, user_id: int, start: date, end: date) -> dict[date, float]:
        rows = await self.db.execute(
            select(Report.report_date, func.coalesce(func.sum(Report.hours), 0))
            .where(Report.user_id == user_id, Report.report_date >= start, Report.report_date <= end)
            .group_by(Report.report_date))
        report_hours = {d: float(h) for d, h in rows.all()}
        overtime_hours = await self.daily_overtime_hours(user_id, start, end)
        merged = dict(report_hours)
        for day, hours in overtime_hours.items():
            merged[day] = merged.get(day, 0.0) + hours
        return merged

    async def daily_pace_labels(self, user_id: int, start: date, end: date) -> dict[date, str]:
        """One label per day: the label of that day's largest-hours report."""
        rows = await self.db.execute(
            select(Report.report_date, AIWorkloadAnalysis.ai_pace_label, Report.hours)
            .join(AIWorkloadAnalysis, AIWorkloadAnalysis.report_id == Report.id)
            .where(Report.user_id == user_id, Report.report_date >= start, Report.report_date <= end))
        best: dict[date, tuple[float, str]] = {}
        for day, label, hours in rows.all():
            if day not in best or hours > best[day][0]:
                best[day] = (hours, label)
        return {d: label for d, (_, label) in best.items()}

    async def pace_distribution(self, user_id: int, start: date, end: date) -> dict[str, float]:
        labels = list((await self.daily_pace_labels(user_id, start, end)).values())
        if not labels:
            return {"heavy": 0.0, "steady": 0.0, "light": 0.0, "unclear": 0.0}
        counts = defaultdict(int)
        for label in labels:
            counts[label] += 1
        n = len(labels)
        return {k: round(counts.get(k, 0) / n, 3) for k in ("heavy", "steady", "light", "unclear")}

    async def attendance_days(self, user_id: int, start: date, end: date, tz: ZoneInfo) -> dict[date, datetime]:
        """Map of local-date -> first check-in (as company-local datetime)."""
        rows = await self.db.execute(
            select(AttendanceSession.check_in_at)
            .where(AttendanceSession.user_id == user_id,
                   AttendanceSession.check_in_at >= datetime.combine(start, time.min, tzinfo=tz),
                   AttendanceSession.check_in_at <= datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)))
        first: dict[date, datetime] = {}
        for (checkin,) in rows.all():
            local = checkin.astimezone(tz)
            day = local.date()
            if day not in first or local < first[day]:
                first[day] = local
        return first

    async def _approved_leave_days(self, user_id: int, start: date, end: date) -> set[date]:
        rows = await self.db.execute(
            select(LeaveRequest.start_date, LeaveRequest.end_date)
            .where(LeaveRequest.user_id == user_id, LeaveRequest.status == "approved",
                   LeaveRequest.start_date <= end, LeaveRequest.end_date >= start))
        days: set[date] = set()
        for s, e in rows.all():
            d = max(s, start)
            while d <= min(e, end):
                days.add(d)
                d += timedelta(days=1)
        return days

    async def attendance_reliability(self, user: User, start: date, end: date) -> dict:
        """See module docstring for the exact definition.

        Reuses AttendanceSession.late_minutes (already computed at check-in
        time via compute_shift_bounds_utc(), with full per-employee
        timezone + company working_hours_mode awareness) instead of
        recalculating on-time status here with a separate, simpler
        company-timezone-only comparison -- the two were drifting apart for
        anyone using a personal timezone override or "local_wall_clock"
        mode, silently producing a wrong reliability percentage for them.
        """
        company = await self._company()
        start = max(start, user.joined_at.date() if user.joined_at else start)
        leave = await self._approved_leave_days(user.id, start, end)

        employee_tz_name = getattr(user, "timezone", None) or company.timezone
        tz = ZoneInfo(employee_tz_name)

        rows = (await self.db.execute(
            select(AttendanceSession.check_in_at, AttendanceSession.late_minutes)
            .where(AttendanceSession.user_id == user.id,
                   AttendanceSession.check_in_at >= datetime.combine(start, time.min, tzinfo=tz),
                   AttendanceSession.check_in_at <= datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz))
        )).all()

        # Map each session to its LOCAL calendar date, keeping the first
        # check-in's late_minutes if a day somehow has more than one session.
        first_late_minutes: dict[date, int | None] = {}
        for checkin, late_minutes in rows:
            local_day = checkin.astimezone(tz).date()
            if local_day not in first_late_minutes:
                first_late_minutes[local_day] = late_minutes

        scheduled = on_time = 0
        d = start
        while d <= end:
            if d.weekday() < 5 and d not in leave:  # weekdays, minus approved leave
                scheduled += 1
                if d in first_late_minutes:
                    late_minutes = first_late_minutes[d]
                    if late_minutes is None or late_minutes <= GRACE_MINUTES:
                        on_time += 1
            d += timedelta(days=1)
        pct = round(on_time / scheduled * 100, 1) if scheduled else 100.0
        return {"scheduled_days": scheduled, "on_time_days": on_time, "reliability_pct": pct}

    # ------------------------------------------------------------------ endpoints
    async def daily_list(self, employee_id: int, start: date, end: date) -> list[dict]:
        await self._target(employee_id)  # tenant + team-scope permission check
        company = await self._company()
        tz = ZoneInfo(company.timezone or "UTC")
        hours = await self.daily_hours(employee_id, start, end)
        paces = await self.daily_pace_labels(employee_id, start, end)
        present = await self.attendance_days(employee_id, start, end, tz)
        leave = await self._approved_leave_days(employee_id, start, end)

        out = []
        d = start
        while d <= end:
            if d in leave:
                status = "on_leave"
            elif d in present:
                status = "present"
            else:
                status = "absent" if d.weekday() < 5 else "non_working_day"
            out.append({"date": str(d), "hours": hours.get(d, 0.0),
                        "workload_pace": paces.get(d), "attendance_status": status})
            d += timedelta(days=1)
        return out

    async def impact_score(self, employee_id: int, start: date, end: date) -> dict:
        """Deterministic weighted score. Formula + weights documented in module docstring."""
        target = await self._target(employee_id)

        report_hours = float(await self.db.scalar(
            select(func.coalesce(func.sum(Report.hours), 0))
            .where(Report.user_id == employee_id,
                   Report.report_date >= start, Report.report_date <= end)) or 0)
        overtime_hours = float(await self.db.scalar(
            select(func.coalesce(func.sum(OvertimeSession.hours), 0))
            .where(OvertimeSession.user_id == employee_id, OvertimeSession.end_at.is_not(None),
                   OvertimeSession.start_at >= datetime.combine(start, time.min),
                   OvertimeSession.start_at <= datetime.combine(end, time.max))) or 0)
        total_hours = report_hours + overtime_hours

        # Team average hours over the same period (fallback: company average).
        # Overtime added into the numerator the same way as the employee's
        # own total above; denominator (distinct contributor count) stays
        # based on regular report submissions, same as before -- someone who
        # ONLY ever logs overtime and never a daily report is an edge case
        # rare enough not to warrant a second distinct-user-count query here.
        peer_filter = (User.team_id == target.team_id) if target.team_id else (User.company_id == self.company_id)
        team_report_total = await self.db.scalar(
            select(func.coalesce(func.sum(Report.hours), 0))
            .join(User, User.id == Report.user_id)
            .where(User.company_id == self.company_id, peer_filter, User.active.is_(True),
                   Report.report_date >= start, Report.report_date <= end))
        team_report_total = float(team_report_total or 0)
        team_contributor_count = await self.db.scalar(
            select(func.greatest(func.count(func.distinct(Report.user_id)), 1))
            .join(User, User.id == Report.user_id)
            .where(User.company_id == self.company_id, peer_filter, User.active.is_(True),
                   Report.report_date >= start, Report.report_date <= end))
        team_overtime_total = await self.db.scalar(
            select(func.coalesce(func.sum(OvertimeSession.hours), 0))
            .join(User, User.id == OvertimeSession.user_id)
            .where(User.company_id == self.company_id, peer_filter, User.active.is_(True),
                   OvertimeSession.end_at.is_not(None),
                   OvertimeSession.start_at >= datetime.combine(start, time.min),
                   OvertimeSession.start_at <= datetime.combine(end, time.max)))
        team_overtime_total = float(team_overtime_total or 0)
        team_avg = (team_report_total + team_overtime_total) / max(int(team_contributor_count or 1), 1)

        dist = await self.pace_distribution(employee_id, start, end)
        recognitions = int(await self.db.scalar(
            select(func.count(Recognition.id))
            .where(Recognition.company_id == self.company_id,
                   Recognition.employee_id == employee_id,
                   Recognition.created_at >= datetime.combine(start, time.min))) or 0)
        reliability = await self.attendance_reliability(target, start, end)

        hours_score = min(total_hours / team_avg, 1.5) / 1.5 * 100 if team_avg > 0 else 50.0
        pace_score = 100 * sum(dist.get(label, 0) * w for label, w in PACE_WEIGHTS.items())
        base = HOURS_WEIGHT * hours_score + PACE_WEIGHT * pace_score
        bonus = 1 + RECOGNITION_BONUS_PER * min(recognitions, 5)
        score = max(0, min(100, round(base * bonus * (reliability["reliability_pct"] / 100))))

        return {
            "impact_score": score,
            "components": {
                "hours_logged": round(total_hours, 1),
                "team_avg_hours": round(team_avg, 1),
                "pace_distribution": {k: dist[k] for k in ("heavy", "steady", "light", "unclear")},
                "recognitions": recognitions,
                "attendance_reliability_pct": reliability["reliability_pct"],
            },
        }

    async def team_comparison(self, team_id: int, start: date, end: date) -> dict:
        team = await self.db.get(Team, team_id)
        if team is None or team.company_id != self.company_id:
            raise HTTPException(status_code=404, detail="Team not found")
        if self.current_user.role == "manager" and self.current_user.team_id != team_id:
            raise HTTPException(status_code=403, detail="Managers can only view their own team")

        members = list((await self.db.execute(
            select(User).where(User.company_id == self.company_id,
                               User.team_id == team_id, User.active.is_(True)))).scalars())
        out = []
        for member in members:
            report_hours = float(await self.db.scalar(
                select(func.coalesce(func.sum(Report.hours), 0))
                .where(Report.user_id == member.id,
                       Report.report_date >= start, Report.report_date <= end)) or 0)
            overtime_hours = float(await self.db.scalar(
                select(func.coalesce(func.sum(OvertimeSession.hours), 0))
                .where(OvertimeSession.user_id == member.id, OvertimeSession.end_at.is_not(None),
                       OvertimeSession.start_at >= datetime.combine(start, time.min),
                       OvertimeSession.start_at <= datetime.combine(end, time.max))) or 0)
            hours = report_hours + overtime_hours
            recognitions = int(await self.db.scalar(
                select(func.count(Recognition.id))
                .where(Recognition.company_id == self.company_id,
                       Recognition.employee_id == member.id,
                       Recognition.created_at >= datetime.combine(start, time.min))) or 0)
            out.append({
                "employee_id": member.id, "name": member.full_name,
                "hours_logged": round(hours, 1),
                "pace_distribution": await self.pace_distribution(member.id, start, end),
                "recognitions": recognitions,
                "attendance_reliability_pct":
                    (await self.attendance_reliability(member, start, end))["reliability_pct"],
            })
        return {"team_id": team_id, "team_name": team.name,
                "period": {"start": str(start), "end": str(end)}, "members": out}