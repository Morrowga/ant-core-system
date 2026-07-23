"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from app.core.config import settings
from app.routers import (admin, admin_auth, ai_insights, alerts, attendance, auth, billing, certificates, company,
                         dashboard, dev_testing, employees, feedback, health, knowledge, holidays, invoices,
                         notifications, onboarding, overtime, performance, projects,
                         recognitions, reports, settings as settings_router_module, support)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG, lifespan=lifespan)

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.ENV == "local" else [],  # tighten per deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth & identity
app.include_router(auth.router)
app.include_router(company.router)
app.include_router(employees.router)

# Attendance & time
app.include_router(attendance.router)
app.include_router(attendance.leave_router)
app.include_router(overtime.router)

# Work
app.include_router(projects.projects_router)
app.include_router(projects.work_threads_router)
app.include_router(reports.router)

# People modules
app.include_router(health.router)
app.include_router(knowledge.knowledge_router)
app.include_router(feedback.router)
app.include_router(certificates.certificates_router)
app.include_router(recognitions.recognitions_router)
app.include_router(onboarding.onboarding_router)
app.include_router(invoices.router)


# Ops
app.include_router(performance.router)
app.include_router(alerts.alerts_router)
app.include_router(dashboard.router)
app.include_router(billing.router)
app.include_router(notifications.router)
app.include_router(settings_router_module.settings_router)
app.include_router(settings_router_module.uploads_router)
app.include_router(holidays.holidays_router)
app.include_router(ai_insights.router)
app.include_router(ai_insights.attendance_absences_router)

# Support (customer-facing ticket submission)
app.include_router(support.router)

# Internal platform-admin app (separate auth, cross-company visibility --
# see app/core/admin_auth.py). Deliberately kept at the bottom, visually
# separated from every customer-facing router above.
app.include_router(admin_auth.router)
app.include_router(admin.router)

# Dev-only manual notification testing -- NO AUTH by design, gated behind
# ENV == "local" inside the router itself as a second layer of protection.
# Remove this router entirely (and the import above) once notification
# testing is done.
app.include_router(dev_testing.router)


@app.get("/healthz", tags=["meta"])
async def healthz():
    return {"status": "ok"}