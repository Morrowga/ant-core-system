"""Import all CORE models so Base.metadata knows every core table
(alembic + create_all). Module-specific models register themselves via
their own modules/<name>/models/__init__.py -- see app/db/migrations/env.py,
which imports both this package and every enabled module's models package.
"""
from app.core.models.organization import Organization  # noqa: F401
from app.core.models.company import (Company, CompanyInvite, CompanySettings,  # noqa: F401
                                     Holiday, PlatformAdmin, Subscription, SupportTicket)
from app.core.models.user import (Consent, DeviceToken, Notification,  # noqa: F401
                                  NotificationPreference, Team, User)
from app.core.models.company_module import CompanyModule  # noqa: F401
from app.core.models.module_assignment import ModuleAssignment  # noqa: F401
from app.core.models.sso import SsoCode  # noqa: F401