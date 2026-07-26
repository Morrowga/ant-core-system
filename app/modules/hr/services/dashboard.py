"""Pulse / scorecard / ask-your-company.

RULE 3 lives here and in integrations/openai_client.py: every number the AI
"answers" with is computed by deterministic SQL first. The LLM only classifies
the question and narrates precomputed metrics — it never does arithmetic.
"""
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select

from app.integrations import openai_client
from app.modules.hr.models.attendance import AttendanceSession, LeaveRequest
from app.modules.hr.models.health import HealthLog
from app.modules.hr.models.misc import AIQueryLog, KnowledgeAcknowledgment, KnowledgePost, Recognition
from app.modules.hr.models.reports import Project, Report
from app.core.models.user import Team, User
from app.core.services.base import TenantService

# Whitelisted query types the classifier may pick from. Each maps to a
# deterministic SQL aggregation below — nothing else is answerable.
# New: goal_progress removed -- Goals as a feature has been removed
# entirely (it only ever tracked hours/time pacing with no financial
# dimension, and Projects now carries real deal price/expense/profit
# tracking instead, which is a stronger signal on its own).
ASKABLE_QUERY_TYPES = ("team_summary", "individual_performance", "project_progress", "company_pulse")

# Wellbeing trend thresholds: mood is on a 1-5 scale; a shift of ±0.15 between
# the last-2-weeks average and the prior-2-weeks average counts as a real move.
WELLBEING_DELTA = 0.15
MIN_TREND_CONTRIBUTORS = 3  # mirror health MIN_AGGREGATE_GROUP: below this, report "stable"


class DashboardService(TenantService):
    # ------------------------------------------------------------ shared helpers
    async def _active_user_ids(self, team_id: int | None = None) -> list[int]:
        stmt = select(User.id).where(User.company_id == self.company_id, User.active.is_(True))
        if team_id is not None:
            stmt = stmt.where(User.team_id == team_id)
        return [r for (r,) in (await self.db.execute(stmt)).all()]

    async def _on_leave_today(self, user_ids: list[int]) -> set[int]:
        if not user_ids:
            return set()
        today = date.today()
        rows = await self.db.execute(
            select(LeaveRequest.user_id).where(
                LeaveRequest.user_id.in_(user_ids), LeaveRequest.status == "approved",
                LeaveRequest.start_date <= today, LeaveRequest.end_date >= today))
        return {r for (r,) in rows.all()}

    async def _attendance_pct(self, team_id: int | None = None) -> float:
        """Distinct employees with a check-in today / active employees expected
        today (active minus those on approved leave)."""
        user_ids = await self._active_user_ids(team_id)
        expected = set(user_ids) - await self._on_leave_today(user_ids)
        if not expected:
            return 0.0
        midnight = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
        checked_in = await self.db.scalar(
            select(func.count(func.distinct(AttendanceSession.user_id)))
            .where(AttendanceSession.user_id.in_(expected),
                   AttendanceSession.check_in_at >= midnight))
        return round((checked_in or 0) / len(expected) * 100, 1)

    async def _report_completion_pct(self, team_id: int | None = None) -> float:
        """Employees who submitted a report today / active employees expected today."""
        user_ids = await self._active_user_ids(team_id)
        expected = set(user_ids) - await self._on_leave_today(user_ids)
        if not expected:
            return 0.0
        reported = await self.db.scalar(
            select(func.count(func.distinct(Report.user_id)))
            .where(Report.user_id.in_(expected), Report.report_date == date.today()))
        return round((reported or 0) / len(expected) * 100, 1)

    async def _wellbeing_trend(self) -> str:
        """Aggregate team mood (1-5) last 2 weeks vs the prior 2 weeks. Never raw
        individual data — only company-wide averages leave this function, and if
        fewer than MIN_TREND_CONTRIBUTORS people logged mood we report 'stable'."""
        now = datetime.now(timezone.utc)

        async def window(start, end):
            row = (await self.db.execute(
                select(func.avg(HealthLog.value), func.count(func.distinct(HealthLog.user_id)))
                .join(User, User.id == HealthLog.user_id)
                .where(User.company_id == self.company_id, HealthLog.type == "mood",
                       HealthLog.logged_at >= start, HealthLog.logged_at < end))).one()
            return (float(row[0]) if row[0] is not None else None, row[1] or 0)

        recent_avg, recent_n = await window(now - timedelta(days=14), now)
        prior_avg, prior_n = await window(now - timedelta(days=28), now - timedelta(days=14))
        if (recent_avg is None or prior_avg is None
                or min(recent_n, prior_n) < MIN_TREND_CONTRIBUTORS):
            return "stable"
        delta = recent_avg - prior_avg
        if delta > WELLBEING_DELTA:
            return "improving"
        if delta < -WELLBEING_DELTA:
            return "declining"
        return "stable"

    async def _project_progress_pct(self) -> float:
        """New: with Goals removed, this always uses what used to be the
        fallback-only path -- the share of active projects with at least
        one report in the last 7 days, as a "reporting cadence" proxy for
        overall project activity."""
        projects = [p for (p,) in (await self.db.execute(
            select(Project.id).where(Project.company_id == self.company_id,
                                     Project.active.is_(True)))).all()]
        if not projects:
            return 0.0
        week_ago = date.today() - timedelta(days=7)
        recently_reported = await self.db.scalar(
            select(func.count(func.distinct(Report.project_id)))
            .where(Report.project_id.in_(projects), Report.report_date >= week_ago))
        return round((recently_reported or 0) / len(projects) * 100, 1)

    async def _knowledge_ack_pct(self) -> float:
        """Acknowledgments recorded / (must-acknowledge posts x active employees)."""
        must_ack_posts = [p for (p,) in (await self.db.execute(
            select(KnowledgePost.id).where(
                KnowledgePost.company_id == self.company_id,
                KnowledgePost.must_acknowledge.is_(True),
                KnowledgePost.deleted_at.is_(None)))).all()]
        actives = len(await self._active_user_ids())
        denominator = len(must_ack_posts) * actives
        if denominator == 0:
            return 100.0
        acks = await self.db.scalar(
            select(func.count(KnowledgeAcknowledgment.id))
            .where(KnowledgeAcknowledgment.post_id.in_(must_ack_posts)))
        return round(min(acks or 0, denominator) / denominator * 100, 1)

    # ------------------------------------------------------------ endpoints
    async def pulse(self) -> dict:
        return {
            "attendance_pct": await self._attendance_pct(),
            "report_completion_pct": await self._report_completion_pct(),
            "project_progress_pct": await self._project_progress_pct(),
            "wellbeing_trend": await self._wellbeing_trend(),
        }

    async def scorecard(self) -> dict:
        return {
            "attendance_pct": await self._attendance_pct(),
            "report_completion_pct": await self._report_completion_pct(),
            "wellbeing_trend": await self._wellbeing_trend(),
            "knowledge_ack_pct": await self._knowledge_ack_pct(),
        }

    # ---------------- ask-your-company ----------------
    async def _entities(self) -> dict:
        """This company's real names — passed to the classifier as the ONLY
        allowed values, so the LLM can't invent a team/employee/project."""
        teams = [t for (t,) in (await self.db.execute(
            select(Team.name).where(Team.company_id == self.company_id))).all()]
        employees = [n for (n,) in (await self.db.execute(
            select(User.full_name).where(User.company_id == self.company_id,
                                         User.active.is_(True),
                                         User.full_name.is_not(None)))).all()]
        projects = [p for (p,) in (await self.db.execute(
            select(Project.name).where(Project.company_id == self.company_id))).all()]
        return {"teams": teams, "employees": employees, "projects": projects}

    async def _compute_metric(self, query_type: str, params: dict) -> dict:
        """Deterministic SQL only. This is the ONLY source of numbers for /ask."""
        if query_type == "company_pulse":
            return {"metric": "company_pulse", **(await self.pulse())}

        if query_type == "team_summary":
            name = (params.get("team_name") or "").strip()
            team = (await self.db.execute(select(Team).where(
                Team.company_id == self.company_id, Team.name.ilike(name)))).scalar_one_or_none()
            if team is None:
                raise HTTPException(status_code=404, detail=f"No team named '{name}'")
            week_ago = date.today() - timedelta(days=7)
            hours = float(await self.db.scalar(
                select(func.coalesce(func.sum(Report.hours), 0))
                .join(User, User.id == Report.user_id)
                .where(User.team_id == team.id, Report.report_date >= week_ago)) or 0)
            return {"metric": "team_summary", "team": team.name,
                    "attendance_pct_today": await self._attendance_pct(team.id),
                    "hours_logged_7d": hours,
                    "report_completion_pct_today": await self._report_completion_pct(team.id)}

        if query_type == "individual_performance":
            from app.modules.hr.services.performance import PerformanceService
            name = (params.get("employee_name") or "").strip()
            target = (await self.db.execute(select(User).where(
                User.company_id == self.company_id, User.active.is_(True),
                User.full_name.ilike(name)))).scalars().first()
            if target is None:
                raise HTTPException(status_code=404, detail=f"No employee named '{name}'")
            if not self.can_view_employee(target):
                raise HTTPException(status_code=403, detail="Not allowed for this employee")
            perf = PerformanceService(self.db, self.current_user)
            start, end = date.today() - timedelta(days=30), date.today()
            hours = float(await self.db.scalar(
                select(func.coalesce(func.sum(Report.hours), 0))
                .where(Report.user_id == target.id, Report.report_date >= start)) or 0)
            recognitions = int(await self.db.scalar(
                select(func.count(Recognition.id))
                .where(Recognition.company_id == self.company_id,
                       Recognition.employee_id == target.id)) or 0)
            return {"metric": "individual_performance", "employee": target.full_name,
                    "period_days": 30, "hours_logged": hours,
                    "attendance": await perf.attendance_reliability(target, start, end),
                    "workload_pace_distribution": await perf.pace_distribution(target.id, start, end),
                    "recognitions": recognitions}

        if query_type == "project_progress":
            name = (params.get("project_name") or "").strip()
            project = (await self.db.execute(select(Project).where(
                Project.company_id == self.company_id, Project.name.ilike(name)))).scalar_one_or_none()
            if project is None:
                raise HTTPException(status_code=404, detail=f"No project named '{name}'")
            hours = float(await self.db.scalar(
                select(func.coalesce(func.sum(Report.hours), 0))
                .where(Report.project_id == project.id)) or 0)
            four_weeks_ago = date.today() - timedelta(days=28)
            recent_reports = int(await self.db.scalar(
                select(func.count(Report.id)).where(
                    Report.project_id == project.id,
                    Report.report_date >= four_weeks_ago)) or 0)
            return {"metric": "project_progress", "project": project.name,
                    "hours_logged_total": hours,
                    "reports_per_week_4w": round(recent_reports / 4, 1)}

        raise HTTPException(status_code=400, detail="Question could not be mapped to a supported metric")

    async def ask(self, question: str) -> dict:
        # 1. LLM classifies question -> one of the whitelisted query types + params
        #    matched against THIS company's real entity names (no numbers involved).
        entities = await self._entities()
        classification = openai_client.classify_question(
            question, list(ASKABLE_QUERY_TYPES), entities=entities)
        query_type = classification.get("query_type")
        if query_type not in ASKABLE_QUERY_TYPES:
            answer = ("Sorry, I can't answer that yet. Try asking about a team, an employee, "
                      "a project, or the overall company pulse.")
            matched = None
            metrics: dict = {}
        else:
            # 2. Deterministic SQL computes the numbers.
            metrics = await self._compute_metric(query_type, classification.get("parameters", {}))
            # 3. LLM narrates the ALREADY-CORRECT numbers (rule 3: narrate(precomputed) only).
            answer = openai_client.narrate(metrics)
            matched = query_type

        log = AIQueryLog(
            company_id=self.company_id, asked_by=self.current_user.id, question_text=question,
            matched_query_type=matched, parameters_json=classification.get("parameters", {}) if matched else {},
            answer_text=answer,
        )
        self.db.add(log)
        await self.db.flush()
        return {"question": question, "matched_query_type": matched, "metrics": metrics, "answer": answer}