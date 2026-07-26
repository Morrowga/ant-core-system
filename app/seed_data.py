"""One-off seed script — creates a single demo company with enough data that
every dashboard page (all 17 groups) has something real to render.

Run inside the API container (so it uses the same DATABASE_URL as the app):

    docker-compose exec api python -m app.seed_data

Safe to re-run: it checks for the demo company by name first and exits without
duplicating data if it already exists. To start fresh, delete the company row
(cascades will clean up the rest) and re-run.
"""
import asyncio
import random
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.modules.hr.models.attendance import AttendanceSession, DeskLocation, LeaveRequest
from app.core.models.company import Company, CompanySettings, Subscription
from app.core.models.company_module import CompanyModule
from app.core.models.organization import Organization
from app.modules.hr.models.health import HealthLog
from app.modules.hr.models.misc import (Alert, AlertSetting, Certificate,
                             EmployeeOnboardingProgress, FeedbackTicket, KnowledgeAcknowledgment, KnowledgePost,
                             OnboardingChecklistItem, Recognition, AIWorkloadAnalysis)
from app.modules.hr.models.reports import Project, Report, ReportComment, WorkThread, WorkThreadEntry
from app.core.models.user import Team, User

ORGANIZATION_NAME = "Northwind Holdings"
COMPANY_NAME = "Northwind Logistics Co."
DEMO_PASSWORD = "Password123!"  # same password for every seeded user, for convenience

PACE_LABELS = ["light", "steady", "steady", "heavy", "unclear"]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(Company).where(Company.name == COMPANY_NAME))).scalar_one_or_none()
        if existing:
            print(f"'{COMPANY_NAME}' already exists (id={existing.id}) — skipping, nothing created.")
            return

        # ---------------------------------------------------------- organization + company
        # Organization must exist before Company (organization_id is
        # NOT NULL on Company) -- but Organization.owner_user_id can't be
        # set until the owner User exists, which itself needs company_id.
        # So: create Organization first with no owner yet, create Company
        # pointing at it, create the owner User, then loop back and set
        # organization.owner_user_id once we actually have that id.
        organization = Organization(name=ORGANIZATION_NAME)
        db.add(organization)
        await db.flush()  # need organization.id

        company = Company(
            organization_id=organization.id,
            name=COMPANY_NAME, industry="Logistics & Supply Chain", timezone="Asia/Ho_Chi_Minh",
            working_hours_start="09:00", working_hours_end="18:00", workdays="mon,tue,wed,thu,fri",
        )
        db.add(company)
        await db.flush()  # need company.id

        subscription = Subscription(
            company_id=company.id, plan_tier="mid", status="active",
            seats_used=8, renews_at=datetime.now(timezone.utc) + timedelta(days=27),
        )
        db.add(subscription)

        # New: also seed the forward-looking CompanyModule row (module_key
        # "hr") alongside the legacy Subscription row above. Nothing reads
        # this yet -- require_active_subscription() still checks
        # Subscription today, per the deliberate not-yet-cut-over decision
        # -- but seeding it now means this demo company is ready the
        # moment that cutover happens, and lets you test the new
        # Organization/CompanyModule schema shape today if you want to.
        db.add(CompanyModule(
            company_id=company.id, module_key="hr", plan_tier="mid", status="active",
            seats_used=8, auto_renew=True,
            current_period_end=datetime.now(timezone.utc) + timedelta(days=27),
            renews_at=datetime.now(timezone.utc) + timedelta(days=27),
        ))

        # Sensible defaults so the Settings page isn't blank on first load.
        default_settings = {
            "attendance": {"default_geofence_radius_m": 75, "away_alert_delay_minutes": 25,
                           "allow_work_outside_override": True, "work_outside_override_roles": ["employee", "manager"]},
            "reporting": {"daily_report_deadline_time": "19:00", "reminder_enabled": True,
                          "require_manager_review": False},
            "overtime": {"allow_self_initiated": True, "require_manager_approval_for_self_initiated": False},
            "health": {"enabled_features": {"water": True, "mood": True, "breaks": True, "steps": True, "sleep": False},
                       "employee_can_opt_out_individually": True},
            "knowledge": {"who_can_post": "admin_and_employee", "default_ack_deadline_days": 7},
            "feedback": {"anonymous_submissions_enabled": True},
            "certificates": {"auto_issue_monthly": True, "auto_issue_yearly": True,
                              "departed_employee_grace_period_days": 60},
            "notifications": {"categories": [
                {"type": "away_from_desk", "enabled_company_wide": True},
                {"type": "missed_check_in", "enabled_company_wide": True},
                {"type": "low_report_completion", "enabled_company_wide": True},
                {"type": "recognition", "enabled_company_wide": True},
            ]},
        }
        for section, data in default_settings.items():
            db.add(CompanySettings(company_id=company.id, section=section, data_json=data))

        for alert_type, delay in [("away_from_desk", 25), ("missed_check_in", 30),
                                   ("forgot_check_out", 60), ("low_report_completion", 0),
                                   ("lateness_pattern", 0), ("overtime_no_report", 0),
                                   ("knowledge_ack_overdue", 0)]:
            db.add(AlertSetting(company_id=company.id, type=alert_type, enabled=True,
                                escalation_delay_minutes=delay, notify_roles="manager,owner_admin"))

        # ---------------------------------------------------------- teams
        eng_team = Team(company_id=company.id, name="Engineering")
        ops_team = Team(company_id=company.id, name="Operations")
        db.add_all([eng_team, ops_team])
        await db.flush()

        # ---------------------------------------------------------- users
        def make_user(email, full_name, role, team_id=None, joined_days_ago=180):
            return User(
                company_id=company.id, organization_id=organization.id,
                email=email, password_hash=hash_password(DEMO_PASSWORD),
                role=role, team_id=team_id, full_name=full_name, active=True,
                joined_at=datetime.now(timezone.utc) - timedelta(days=joined_days_ago),
            )

        owner = make_user("owner@northwind.demo", "Alex Tran", "owner_admin", joined_days_ago=400)
        eng_manager = make_user("eng.manager@northwind.demo", "Priya Nair", "manager", eng_team.id, 300)
        ops_manager = make_user("ops.manager@northwind.demo", "Marcus Webb", "manager", ops_team.id, 300)
        employees = [
            make_user("sofia@northwind.demo", "Sofia Reyes", "employee", eng_team.id, 200),
            make_user("daniel@northwind.demo", "Daniel Kim", "employee", eng_team.id, 150),
            make_user("linh@northwind.demo", "Linh Pham", "employee", eng_team.id, 90),
            make_user("grace@northwind.demo", "Grace Obi", "employee", ops_team.id, 220),
            make_user("tomas@northwind.demo", "Tomas Novak", "employee", ops_team.id, 60),
        ]
        new_hire = make_user("new.hire@northwind.demo", "Jordan Blake", "employee", eng_team.id, 6)
        db.add_all([owner, eng_manager, ops_manager, *employees, new_hire])
        await db.flush()

        # Now that the owner User row exists, wire the Organization back
        # to it -- couldn't be done earlier since Organization was created
        # before any User did.
        organization.owner_user_id = owner.id

        eng_team.manager_id = eng_manager.id
        ops_team.manager_id = ops_manager.id

        all_reporting_users = [eng_manager, ops_manager, *employees]  # everyone who logs work like an employee

        for u in [owner, eng_manager, ops_manager, *employees, new_hire]:
            db.add(DeskLocation(user_id=u.id, lat=10.7626 + random.uniform(-0.001, 0.001),
                                 lng=106.6602 + random.uniform(-0.001, 0.001)))

        # ---------------------------------------------------------- projects & goals
        proj_mobile = Project(company_id=company.id, name="Mobile App v2", description="Rebuild of the driver app", active=True)
        proj_wms = Project(company_id=company.id, name="Warehouse Management System", description="Internal WMS rollout", active=True)
        proj_support = Project(company_id=company.id, name="Client Support", description="Ongoing client support & fixes", active=True)
        db.add_all([proj_mobile, proj_wms, proj_support])
        await db.flush()

        # ---------------------------------------------------------- reports, attendance, health (last 14 days)
        today = date.today()
        for day_offset in range(14, 0, -1):
            day = today - timedelta(days=day_offset)
            if day.weekday() >= 5:  # skip weekends
                continue
            for u in all_reporting_users:
                # ~90% chance this person worked & reported that day
                if random.random() < 0.1:
                    continue

                check_in = datetime.combine(day, time(9, random.randint(0, 20)), tzinfo=timezone.utc)
                check_out = datetime.combine(day, time(17, random.randint(30, 59)), tzinfo=timezone.utc)
                db.add(AttendanceSession(user_id=u.id, check_in_at=check_in, check_out_at=check_out,
                                          desk_lat=10.7626, desk_lng=106.6602))

                project = random.choice([proj_mobile, proj_wms, proj_support])
                hours = round(random.uniform(4, 9), 1)
                summaries = [
                    "Fixed login bug on the driver app, verified with QA.",
                    "Found more edge cases in the firebase notification flow, still investigating.",
                    "Reviewed PRs and paired with teammate on the warehouse scan screen.",
                    "Client reported sync issue, root-caused to a stale cache key.",
                    "Continued work on notification delivery reliability, added retry logic.",
                    "Wrote tests for the new checkout flow, coverage now above 80%.",
                    "Investigated slow query on the reports endpoint, added an index.",
                ]
                report = Report(
                    user_id=u.id, project_id=project.id, hours=hours,
                    summary=random.choice(summaries), report_date=day,
                    editable_until=datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone.utc),
                    created_at=check_out,
                )
                db.add(report)
                await db.flush()

                pace = random.choice(PACE_LABELS)
                db.add(AIWorkloadAnalysis(
                    report_id=report.id, hours=hours, ai_pace_label=pace,
                    ai_reasoning_text=f"Reported {hours}h with a {pace} level of described effort relative to team norms.",
                    model_version="gpt-4o-seed",
                ))

                # health logs
                db.add(HealthLog(user_id=u.id, type="water", value=random.randint(4, 10) * 250,
                                  logged_at=check_in + timedelta(hours=2)))
                db.add(HealthLog(user_id=u.id, type="mood", value=random.randint(3, 5),
                                  logged_at=check_in + timedelta(hours=1)))

        # A visible "same work, different wording" continuity thread
        thread_reports = (await db.execute(
            select(Report).where(Report.summary.ilike("%firebase notification%")).order_by(Report.report_date)
        )).scalars().all()
        if len(thread_reports) >= 2:
            thread = WorkThread(user_id=thread_reports[0].user_id, project_id=thread_reports[0].project_id,
                                 title="Firebase notification reliability",
                                 first_seen_date=thread_reports[0].report_date,
                                 last_seen_date=thread_reports[-1].report_date, status="active")
            db.add(thread)
            await db.flush()
            for r in thread_reports:
                db.add(WorkThreadEntry(thread_id=thread.id, report_id=r.id, similarity_score=0.86))

        # A manager comment, for the Reports detail page
        if thread_reports:
            db.add(ReportComment(report_id=thread_reports[-1].id, author_id=eng_manager.id,
                                  comment="Let's pair on this tomorrow if it's still open."))

        # ---------------------------------------------------------- leave & overtime-adjacent alert data
        db.add(LeaveRequest(user_id=employees[2].id, type="sick", start_date=today + timedelta(days=2),
                             end_date=today + timedelta(days=2), status="pending"))
        db.add(LeaveRequest(user_id=employees[0].id, type="annual", start_date=today - timedelta(days=20),
                             end_date=today - timedelta(days=18), status="approved"))

        db.add(Alert(company_id=company.id, user_id=employees[3].id, type="away_from_desk", status="open"))
        db.add(Alert(company_id=company.id, user_id=employees[4].id, type="low_report_completion", status="acknowledged"))

        # ---------------------------------------------------------- knowledge sharing
        post1 = KnowledgePost(company_id=company.id, author_id=owner.id,
                               title="Employee Handbook — Leave Policy", body="Full leave policy details...",
                               category="HR", pinned=True, must_acknowledge=True, ack_deadline_days=7)
        post2 = KnowledgePost(company_id=company.id, author_id=eng_manager.id,
                               title="Engineering: Local Dev Setup", body="How to set up your local environment...",
                               category="Engineering", pinned=False, must_acknowledge=False)
        db.add_all([post1, post2])
        await db.flush()
        for u in employees:
            db.add(KnowledgeAcknowledgment(post_id=post1.id, user_id=u.id))
        # Intentionally leave the new hire's ack missing, so the ack-status view has a gap to show.

        # ---------------------------------------------------------- recognition
        db.add(Recognition(company_id=company.id, given_by=eng_manager.id, employee_id=employees[0].id,
                            reason="Great root-cause work on the client sync issue this week."))
        db.add(Recognition(company_id=company.id, given_by=owner.id, employee_id=employees[1].id,
                            reason="Consistently high-quality PRs and reviews."))

        # ---------------------------------------------------------- feedback (one anonymous)
        db.add(FeedbackTicket(company_id=company.id, user_id=None, category="workload",
                               message="Our team has been stretched thin the last two sprints.",
                               anonymous=True, status="open"))
        db.add(FeedbackTicket(company_id=company.id, user_id=employees[3].id, category="general",
                               message="Would love a better way to search old knowledge posts.",
                               anonymous=False, status="seen"))

        # ---------------------------------------------------------- onboarding
        item1 = OnboardingChecklistItem(company_id=company.id, title="Read the Employee Handbook",
                                         type="read", linked_knowledge_post_id=post1.id, required=True, order=1)
        item2 = OnboardingChecklistItem(company_id=company.id, title="Set your desk location",
                                         type="task", required=True, order=2)
        item3 = OnboardingChecklistItem(company_id=company.id, title="Submit your first daily report",
                                         type="task", required=True, order=3)
        db.add_all([item1, item2, item3])
        await db.flush()
        db.add(EmployeeOnboardingProgress(user_id=new_hire.id, checklist_item_id=item2.id))
        # item1 and item3 intentionally left incomplete for new_hire, so the onboarding page shows partial progress.

        # ---------------------------------------------------------- a sample certificate for a long-tenured employee
        db.add(Certificate(
            user_id=employees[0].id, period_type="monthly",
            period_start=today.replace(day=1) - timedelta(days=32),
            period_end=today.replace(day=1) - timedelta(days=1),
            data_json={"hours_logged": 148, "attendance_reliability_pct": 96,
                       "workload_pace": "steady", "recognitions": 1, "overtime_hours": 4},
            pdf_url=None,
        ))

        await db.commit()

        print(f"Seeded organization '{ORGANIZATION_NAME}' / company '{COMPANY_NAME}' "
              f"(organization_id={organization.id}, company_id={company.id}) successfully.\n")
        print("Login credentials (same password for all):")
        print(f"  password: {DEMO_PASSWORD}\n")
        print(f"  Owner/Admin : {owner.email}")
        print(f"  Manager (Eng): {eng_manager.email}")
        print(f"  Manager (Ops): {ops_manager.email}")
        for u in employees:
            print(f"  Employee    : {u.email}")
        print(f"  New hire    : {new_hire.email}  (in first 30 days, onboarding in progress)")


if __name__ == "__main__":
    asyncio.run(main())