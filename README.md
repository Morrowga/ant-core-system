# Workforce Platform — Backend Scaffold

FastAPI + async SQLAlchemy 2.0 + PostgreSQL (pgvector) + Redis + Celery + Stripe + Firebase + OpenAI.
Multi-tenant B2B SaaS: dashboard API (owner/manager) + employee-facing mobile/web API.

## Run locally

```bash
cp .env.example .env          # fill JWT secret; Stripe/Firebase/OpenAI keys optional for local dev
docker compose up --build
```

That starts Postgres (pgvector), Redis, the API (runs `alembic upgrade head` on boot), a Celery
worker, and Celery beat. API at http://localhost:8000 — interactive docs at `/docs`.

Without Docker:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# point DATABASE_URL / REDIS_URL in .env at local services, then:
alembic upgrade head
uvicorn app.main:app --reload
celery -A app.workers.celery_app.celery_app worker -l info   # separate shell
celery -A app.workers.celery_app.celery_app beat -l info     # separate shell
```

No OpenAI/Stripe/Firebase keys? Everything still runs: the OpenAI client falls back to
deterministic local stubs, Stripe subscribe marks subscriptions active locally, and pushes
log as no-ops.

## Try the end-to-end example flow

```bash
# 1. Register a company (creates owner + trial subscription, returns tokens)
curl -s localhost:8000/auth/register -H 'content-type: application/json' -d '{
  "company_name":"Acme","timezone":"Asia/Ho_Chi_Minh",
  "owner_email":"owner@acme.test","owner_password":"password123"}'

export TOKEN=<access_token from above>
AUTH="Authorization: Bearer $TOKEN"

# 2. Check in
curl -s -X POST localhost:8000/attendance/check-in -H "$AUTH" -H 'content-type: application/json' -d '{}'

# 3. Create a project, submit a daily report (queues AI workload analysis + thread matching)
curl -s -X POST localhost:8000/projects -H "$AUTH" -H 'content-type: application/json' \
  -d '{"name":"Platform build"}'
curl -s -X POST localhost:8000/reports -H "$AUTH" -H 'content-type: application/json' \
  -d '[{"project_id":1,"hours":6.5,"summary":"Scaffolded auth and attendance modules"}]'

# 4. View it on the dashboard with the AI pace label
curl -s localhost:8000/dashboard/pulse -H "$AUTH"
curl -s localhost:8000/reports/1 -H "$AUTH"
```

## Changelog — repair pass (2026-07-14)

**Fixed**
- `app/routers/settings.py` upload endpoint crashed at runtime: `os`/`uuid` were used but never imported. Ran a pyflakes undefined-name sweep across `app/` — this was the only real bug; unused imports left over from the router split were also cleaned up.

**Added**
- Goals: `GET/PATCH/DELETE /goals/{id}` (delete = archive, never hard-deletes) and `DELETE /goals/{id}/link-project/{project_id}`. Goals gained an optional `target_hours` so progress % has a real denominator.
- Performance module (`routers/performance.py` + `services/performance.py`): daily list, Impact Score, team comparison, attendance reliability. All deterministic SQL/arithmetic — the exact Impact Score weights and the attendance-reliability definition are documented in the `services/performance.py` module docstring. Manager access is scoped to their own team via the existing `can_view_employee` helpers.
- Onboarding admin side: checklist CRUD under `/company/settings/onboarding-checklist` (mutations Owner-only), `GET /onboarding/{employee_id}` (completion %, days since joined, 14-day pace trend, `reached_team_baseline_on` = first day the employee's daily hours met the team's average daily hours), `GET /onboarding?status=in_progress` (first-30-days employees).
- Knowledge posts: `PATCH` (author or dashboard roles) and `DELETE` (soft delete via `deleted_at`; hidden from all reads, acknowledgments preserved).
- Billing: `GET /billing/invoices` (Stripe invoice list) and `PATCH /billing/payment-method` (SetupIntent two-step flow; both no-op gracefully without Stripe keys).
- Certificates: `GET /certificates/{id}/download` — streams a local file from `UPLOAD_DIR` or redirects to a hosted URL; returns 409 while the PDF renderer is still a TODO in the issuance task.
- Notification preferences: `GET/PATCH /notifications/preferences`. Attendance/payroll-adjacent categories are hardcoded as non-mutable (`services/notifications.py::NON_MUTABLE_CATEGORIES`) and `send()` enforces mutes centrally.
- Migration `0002` (notification_preferences table, `knowledge_posts.deleted_at`, `goals.target_hours`) — guarded so it's a no-op on fresh installs.

**Changed**
- `GET /dashboard/pulse` now returns `attendance_pct`, `report_completion_pct`, `project_progress_pct`, `wellbeing_trend` (spec shape). Denominators exclude employees on approved leave. `project_progress_pct` averages goal progress when active goals exist, else falls back to the share of active projects reported on in the last 7 days (documented in code).
- `GET /dashboard/scorecard` now returns the 5-tile shape (attendance, report completion, per-goal progress/on-track, wellbeing trend, knowledge ack %). Shares the same helpers as pulse — no duplicated queries.
- `wellbeing_trend` compares the aggregated team mood average of the last 2 weeks vs the prior 2 weeks (±0.15 threshold), reports "stable" when fewer than 3 people contributed — never touches raw individual health rows.
- `POST /dashboard/ask` whitelist replaced with `team_summary`, `individual_performance`, `project_progress`, `goal_progress`, `company_pulse`. The classifier now receives the company's real team/employee/project/goal names as the only allowed parameter values (`classify_question(..., entities=...)`), with a server-side guard that drops any invented name — and every name is re-resolved against the DB regardless. Same rule-3 pattern throughout: LLM classifies, SQL computes, LLM narrates.

## Architecture decisions

**Celery (not APScheduler).** The system needs event-driven jobs (AI workload analysis and
work-thread matching fired per report submit) *and* scheduled jobs (alert escalation sweeps,
monthly/yearly certificate auto-issuance). Celery + Redis covers both via `.delay()` and beat,
survives multi-instance API deployments, and Redis is already in the stack — zero extra infra.
APScheduler runs in-process and only covers the scheduled half cleanly.

**pgvector (not JSON columns).** Report-summary embeddings (`text-embedding-3-small`, 1536-dim)
live in `report_embeddings.embedding vector(1536)`; work-thread matching runs cosine-distance
nearest-neighbor directly in SQL (`ORDER BY embedding <=> :vec`). docker-compose ships the
`pgvector/pgvector:pg16` image so availability is guaranteed; the initial migration runs
`CREATE EXTENSION IF NOT EXISTS vector`. If you must target a Postgres without pgvector, swap
the column for a JSON array and compute cosine similarity in `app/services/work_threads.py`.

**Multi-tenancy.** Single shared database; every tenant-scoped table carries `company_id`.
`app/services/base.py::TenantService` is constructed with the JWT-authenticated user and exposes
`tenant_select()` / `tenant_select_via_user()` so every query is tenant-filtered at the
service/repository layer — the client can never supply a `company_id`.

**Roles.** Exactly three: `owner_admin`, `manager`, `employee`, enforced by the
`require_role([...])` dependency on every dashboard route. Managers also use the full
employee-side API (check-in, reports, health) and get team-scoped dashboard visibility.

## Business rules — where they're enforced

| # | Rule | Enforced in |
|---|------|-------------|
| 1 | Location pings only between check-in/out | `services/attendance.py::record_ping` (409 otherwise) |
| 2 | Overtime can't close without a report | `services/overtime.py::end` (409 until summary attached) |
| 3 | AI never computes numbers | `integrations/openai_client.py` signatures (`narrate(precomputed_metrics)`, no `compute_and_narrate`); deterministic SQL in `services/dashboard.py`, `services/ai_workload.py`; embeddings + SQL cosine sim in `services/work_threads.py` |
| 4 | Reports same-day editable only | `services/reports.py` — `editable_until` = next local midnight (company tz), PATCH/DELETE 403 after |
| 5 | No raw health data to non-owners | `services/health.py` — team route returns aggregates only, min group size 3; no per-user route exists for managers |
| 6 | Certificates auto-issue, no gate | `workers/tasks/certificates.py` (beat); no approval endpoint exists |
| 7 | Presence-aware push routing | `services/notifications.py::send` — the only FCM entry point |
| 8 | Plan gating | `core/dependencies.py::require_plan_feature` + `PLAN_FEATURES` map (tiers adjustable there) |
| 9 | Harassment feedback → Owner only | `services/feedback.py` — hardcoded `OWNER_ONLY_CATEGORIES`, filtered at query level |
| 10 | Anonymous feedback stays anonymous | `services/feedback.py` — `user_id` never stored; `created_at` coarsened to the hour to block timestamp cross-referencing |

## Layout

```
app/
  core/          config, JWT/passwords, dependencies (auth, roles, plan gating)
  db/            base + session + alembic migrations
  models/        SQLAlchemy models by domain
  schemas/       Pydantic v2 request/response models
  services/      business logic + tenant scoping (routers stay thin)
  routers/       one file per API domain
  workers/       celery app + tasks (alerts, certificates, AI workload, thread matching)
  integrations/  openai_client, stripe_client, firebase
  tests/         smoke tests (SQLite in-memory)
```

## Migrations

Initial migration (`0001`) creates the full schema from `Base.metadata` and enables pgvector.
For subsequent changes: `alembic revision --autogenerate -m "..."` then `alembic upgrade head`.

## Phase 2 / open items (mirrors the API doc)

- 1-on-1 scheduling, cross-team workload balancing, attrition signals — out of scope.
- Departed-employee data retention: currently soft-delete (`users.active=false`, data kept). Revisit.
