"""Health data. Enforces rule 5: raw rows are self-only; team views are aggregates.

MIN_AGGREGATE_GROUP protects small teams: if fewer than N members contributed
data on a day, that day's aggregate is suppressed so values can't be traced to
an individual.
"""
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.health import HealthLog
from app.models.users import User
from app.schemas.health import TeamWellbeingPoint
from app.services.base import TenantService

MIN_AGGREGATE_GROUP = 3


class HealthService(TenantService):
    # ---------- self-only (employee-facing) ----------
    async def log(self, type_: str, value: float) -> HealthLog:
        row = HealthLog(user_id=self.current_user.id, type=type_, value=value)
        self.db.add(row)
        await self.db.flush()
        return row

    async def my_logs(self, type_: str, since_days: int = 14) -> list[HealthLog]:
        since = datetime.utcnow() - timedelta(days=since_days)
        res = await self.db.execute(
            select(HealthLog).where(
                HealthLog.user_id == self.current_user.id,   # self-only, always
                HealthLog.type == type_,
                HealthLog.logged_at >= since,
            ).order_by(HealthLog.logged_at.desc())
        )
        return list(res.scalars())

    async def my_dashboard(self) -> dict:
        # Steps removed entirely -- not relevant for a desk-based team, and
        # was never actually wired up to a real pedometer/step-count source
        # anywhere in the mobile app to begin with.
        out: dict = {}
        for t in ("water", "mood", "sleep"):
            logs = await self.my_logs(t, since_days=7)
            out[t] = [{"value": l.value, "logged_at": l.logged_at.isoformat()} for l in logs]
        return out

    # ---------- team view (dashboard) — AGGREGATED ONLY (rule 5) ----------
    async def team_wellbeing_trend(self, team_id: int | None = None, days: int = 30) -> list[TeamWellbeingPoint]:
        # Managers may only query their own team.
        if self.current_user.role == "manager":
            if team_id is not None and team_id != self.current_user.team_id:
                raise HTTPException(status_code=403, detail="Managers can only view their own team")
            team_id = self.current_user.team_id

        since = date.today() - timedelta(days=days)
        day = func.date(HealthLog.logged_at).label("day")

        stmt = (
            select(
                day,
                HealthLog.type,
                func.avg(HealthLog.value).label("avg_value"),
                func.count(func.distinct(HealthLog.user_id)).label("contributors"),
            )
            .join(User, User.id == HealthLog.user_id)
            .where(
                User.company_id == self.company_id,   # tenant boundary in SQL
                HealthLog.logged_at >= since,
                HealthLog.type.in_(("water", "mood", "sleep")),
            )
        )
        if team_id is not None:
            stmt = stmt.where(User.team_id == team_id)

        stmt = stmt.group_by(day, HealthLog.type).order_by(day)
        rows = (await self.db.execute(stmt)).all()

        by_day: dict[str, dict] = {}
        for r in rows:
            if r.contributors < MIN_AGGREGATE_GROUP:
                continue  # suppress small groups — anonymity floor
            d = str(r.day)
            entry = by_day.setdefault(d, {"date": d, "avg_mood": None, "avg_water_ml": None,
                                          "avg_sleep_hours": None, "sample_size": 0})
            if r.type == "mood":
                entry["avg_mood"] = round(float(r.avg_value), 2)
            elif r.type == "water":
                entry["avg_water_ml"] = round(float(r.avg_value), 1)
            elif r.type == "sleep":
                entry["avg_sleep_hours"] = round(float(r.avg_value), 2)
            entry["sample_size"] = max(entry["sample_size"], int(r.contributors))

        return [TeamWellbeingPoint(**v) for v in by_day.values()]