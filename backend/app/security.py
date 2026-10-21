"""Session authentication, CSRF checks, and reusable ownership enforcement."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.app.database import get_db
from backend.app.models.session import AuthSession
from backend.app.models.user import User

SESSION_COOKIE = "edupath_session"
CSRF_COOKIE = "edupath_csrf"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_csrf_pair(request: Request, expected_hash: str | None = None) -> str:
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    header_token = request.headers.get("X-CSRF-Token", "")
    if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    if expected_hash and not hmac.compare_digest(token_digest(header_token), expected_hash):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return header_token


def require_anonymous_csrf(request: Request) -> None:
    """Protect login and registration against cross-site form submission."""
    verify_csrf_pair(request)


@dataclass(frozen=True)
class AuthenticatedContext:
    user: User
    session: AuthSession


def get_authenticated_context(
    request: Request,
    db: Session = Depends(get_db),
) -> AuthenticatedContext:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    auth_session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_digest(raw_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
    )
    if auth_session is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = db.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        if auth_session.revoked_at is None:
            auth_session.revoked_at = utcnow()
            db.commit()
        raise HTTPException(status_code=401, detail="Authentication required")

    request.state.current_user_id = user.id
    return AuthenticatedContext(user=user, session=auth_session)


def get_current_user(context: AuthenticatedContext = Depends(get_authenticated_context)) -> User:
    return context.user


def require_authenticated_csrf(
    request: Request,
    context: AuthenticatedContext = Depends(get_authenticated_context),
) -> AuthenticatedContext:
    verify_csrf_pair(request, expected_hash=context.session.csrf_token_hash)
    return context


def assert_resource_owner(resource_owner_id: UUID, current_user: User) -> None:
    """Return 404 rather than 403 to avoid confirming another user's resource exists."""
    if resource_owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resource not found")


def issue_session(
    db: Session,
    user: User,
    settings: Settings,
) -> tuple[AuthSession, str, str]:
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    now = utcnow()
    session = AuthSession(
        user_id=user.id,
        token_hash=token_digest(session_token),
        csrf_token_hash=token_digest(csrf_token),
        created_at=now,
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(session)
    return session, session_token, csrf_token


def set_auth_cookies(request: Request, response, session_token: str, csrf_token: str, settings: Settings) -> None:
    secure = settings.app_env == "production"
    response.set_cookie(key=SESSION_COOKIE, value=session_token,
                        max_age=settings.session_ttl_hours * 3600, httponly=True,
                        secure=secure, samesite="lax", path="/")
    response.set_cookie(key=CSRF_COOKIE, value=csrf_token,
                        max_age=settings.session_ttl_hours * 3600, httponly=False,
                        secure=secure, samesite="lax", path="/")
