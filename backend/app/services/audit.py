"""Security audit writer that stores only event type, user id, and keyed IP digest."""
from __future__ import annotations

import hashlib
import hmac
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.models.audit_event import SecurityAuditEvent


def record_security_event(
    db: Session,
    request: Request,
    settings: Settings,
    event_type: str,
    user_id: UUID | None = None,
) -> None:
    """Queue a low-PII security event in the current transaction."""
    host = request.client.host if request.client else "unknown"
    key = settings.secret_key.get_secret_value().encode("utf-8")
    if not key:
        key = b"edupath-development-only-ip-hash-key"
    ip_digest = hmac.new(key, host.encode("utf-8", errors="ignore"), hashlib.sha256).hexdigest()
    db.add(SecurityAuditEvent(event_type=event_type, user_id=user_id, ip_hash=ip_digest))
