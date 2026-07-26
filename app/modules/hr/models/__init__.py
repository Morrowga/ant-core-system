"""Import all HR-module models so Base.metadata knows every HR table
(alembic + create_all). Moved from the old top-level app/models/__init__.py
as part of the Organization/module restructuring -- same imports, same
tables, no field changes.
"""
from app.modules.hr.models.attendance import (AttendanceSession, DeskLocation,  # noqa: F401
                                               DeskLocationRequest, LeaveRequest, LocationPing,
                                               PresenceCheckPrompt, WorkOutsideOverride)
from app.modules.hr.models.reports import (OvertimeRequest, OvertimeSession, Project,  # noqa: F401
                                            ProjectAssignment, ProjectExpense, Report,
                                            ReportComment, ReportEmbedding, WorkThread, WorkThreadEntry)
from app.modules.hr.models.health import HealthLog  # noqa: F401
from app.modules.hr.models.misc import (AIQueryLog, AIWorkloadAnalysis, Alert, AlertSetting,  # noqa: F401
                                         Certificate, EmployeeOnboardingProgress, FeedbackTicket,
                                         HealthCheckinPrompt, Invoice, KnowledgeAcknowledgment,
                                         KnowledgeComment, KnowledgePost, OnboardingChecklistItem,
                                         Recognition)
from app.modules.hr.models.ai_insights import CompanyOverviewAnalysis, ProjectAnalysis  # noqa: F401
