"""Import all mapped classes so Alembic discovers every table."""
from backend.app.models.base import Base
from backend.app.models.user import User
from backend.app.models.session import AuthSession
from backend.app.models.audit_event import SecurityAuditEvent
from backend.app.models.student_profile import StudentProfile
from backend.app.models.conversation import Conversation, ConversationMessage
from backend.app.models.legacy_application_state import LegacyApplicationState

__all__ = [
    "Base",
    "User",
    "AuthSession",
    "SecurityAuditEvent",
    "StudentProfile",
    "Conversation",
    "ConversationMessage",
    "LegacyApplicationState",
]
