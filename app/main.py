"""FastAPI application entrypoint.

Restructured for the Organization/module split: app.core.routers holds
everything cross-cutting (auth, company/org identity, billing, platform
admin, support). app.modules.hr.routers holds everything that is
specifically the HR module's feature set -- unchanged behavior, just
relocated. Future modules (Warehouse, POS, ...) each get their own
app.modules.<name>.routers imported and mounted the same way.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from app.core.config import settings
from app.core.routers import admin, admin_auth, auth, billing, company, dev_testing, organizations, sso, support
from app.modules.hr.routers import (ai_insights, alerts, attendance, certificates, dashboard,
                                    employees, feedback, health, holidays, invoices, knowledge,
                                    notifications, onboarding, overtime, performance, projects,
                                    recognitions, reports, settings as settings_router_module)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG, lifespan=lifespan)

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

app.add_middleware(
    CORSMiddleware,
    # Was `[]` for production -- meaning NO origin was ever actually
    # allowed once ENV=production, not just Core Dashboard specifically.
    # This had never been filled in for the real deployment. Add Portal's
    # and HR Dashboard's URLs here too once they're live.
    allow_origins=["*"] if settings.ENV == "local" else [
        "https://ants-core-ui-nine.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================================================================== Core
# Identity, organization/company structure, billing, platform admin.
# Cross-cutting -- not owned by any one module.
app.include_router(auth.router)
app.include_router(sso.router)
app.include_router(company.router)
app.include_router(billing.router)
app.include_router(organizations.router) 

# ==================================================================== HR module
# Everything below is the HR module's feature set, unchanged in behavior --
# only relocated under app/modules/hr/.
app.include_router(employees.router)

app.include_router(attendance.router)
app.include_router(attendance.leave_router)
app.include_router(overtime.router)

app.include_router(projects.projects_router)
app.include_router(projects.work_threads_router)
app.include_router(reports.router)

app.include_router(health.router)
app.include_router(knowledge.knowledge_router)
app.include_router(feedback.router)
app.include_router(certificates.certificates_router)
app.include_router(recognitions.recognitions_router)
app.include_router(onboarding.onboarding_router)
app.include_router(invoices.router)

app.include_router(performance.router)
app.include_router(alerts.alerts_router)
app.include_router(dashboard.router)
app.include_router(notifications.router)
app.include_router(settings_router_module.settings_router)
app.include_router(settings_router_module.uploads_router)
app.include_router(holidays.holidays_router)
app.include_router(ai_insights.router)
app.include_router(ai_insights.attendance_absences_router)

# ==================================================================== Core (continued)
# Support (customer-facing ticket submission) -- not HR-specific, any
# company can reach the platform operator regardless of which modules it has.
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