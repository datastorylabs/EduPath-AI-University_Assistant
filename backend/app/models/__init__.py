"""Import all mapped classes so Alembic discovers every table."""
from backend.app.models.base import Base
from backend.app.models.user import User
from backend.app.models.session import AuthSession
from backend.app.models.audit_event import SecurityAuditEvent

__all__ = ["Base", "User", "AuthSession", "SecurityAuditEvent"]
