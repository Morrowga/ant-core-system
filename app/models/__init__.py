"""Import all models so Base.metadata knows every table (alembic + create_all)."""
from app.models.company import Company, CompanyInvite, CompanySettings, Subscription  # noqa: F401
from app.models.users import Consent, DeviceToken, Notification, Team, User  # noqa: F401
from app.models.attendance import (AttendanceSession, DeskLocation, LeaveRequest,  # noqa: F401
                                   LocationPing, WorkOutsideOverride)
from app.models.reports import (OvertimeSession, Project, ProjectAssignment, ProjectExpense,  # noqa: F401
                                Report, ReportComment, ReportEmbedding, WorkThread, WorkThreadEntry)
from app.models.health import HealthLog  # noqa: F401
from app.models.misc import (AIQueryLog, AIWorkloadAnalysis, Alert, AlertSetting,  # noqa: F401
                             Certificate, EmployeeOnboardingProgress, FeedbackTicket, Invoice,
                             KnowledgeAcknowledgment, KnowledgeComment,
                             KnowledgePost, OnboardingChecklistItem, Recognition)
from app.models.ai_insights import CompanyOverviewAnalysis, ProjectAnalysis  # noqa: F401