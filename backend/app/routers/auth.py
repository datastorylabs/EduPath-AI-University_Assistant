"""Registration, login, logout, CSRF bootstrap, and current-user endpoints."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.app.database import get_db
from backend.app.models.session import AuthSession
from backend.app.models.user import User
from backend.app.schemas import AuthResponse, LoginRequest, RegisterRequest, UserResponse
from backend.app.security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    AuthenticatedContext,
    get_authenticated_context,
    issue_session,
    require_anonymous_csrf,
    require_authenticated_csrf,
    set_auth_cookies,
    token_digest,
    utcnow,
)
from backend.app.services.audit import record_security_event
from backend.app.services.passwords import hash_password, password_hash_needs_rehash, verify_password
from backend.app.services.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/auth", tags=["authentication"])

# Use a real Argon2id hash for unknown accounts to reduce username-enumeration timing differences.
_DUMMY_PASSWORD_HASH = hash_password("edupath-dummy-password-never-used-for-login")


def _csrf_rate_limit(request: Request) -> None:
    enforce_rate_limit(request, "csrf", 60)


def _register_rate_limit(request: Request) -> None:
    enforce_rate_limit(request, "register", get_settings().register_rate_limit)


def _login_rate_limit(request: Request) -> None:
    enforce_rate_limit(request, "login", get_settings().login_rate_limit)


def _create_login_response(
    request: Request,
    response: Response,
    db: Session,
    user: User,
    settings: Settings,
    event_type: str,
) -> AuthResponse:
    auth_session, session_token, csrf_token = issue_session(db, user, settings)
    record_security_event(db, request, settings, event_type, user_id=user.id)
    db.commit()
    db.refresh(user)
    db.refresh(auth_session)
    set_auth_cookies(request, response, session_token, csrf_token, settings)
    return AuthResponse(user=UserResponse.from_user(user), csrf_token=csrf_token, expires_at=auth_session.expires_at)


@router.get("/csrf", dependencies=[Depends(_csrf_rate_limit)])
def get_csrf_token(response: Response, settings: Settings = Depends(get_settings)) -> dict[str, str]:
    """Bootstrap a double-submit CSRF token before login or registration."""
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        key=CSRF_COOKIE,
        value=csrf_token,
        max_age=1800,
        httponly=False,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/",
    )
    return {"csrf_token": csrf_token}


@router.post(
    "/register",
    status_code=201,
    response_model=AuthResponse,
    dependencies=[Depends(_register_rate_limit), Depends(require_anonymous_csrf)],
)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    """Create a user and an opaque session after validation and CSRF checks."""
    user = User(
        email=str(payload.email).strip().lower(),
        password_hash=hash_password(payload.password.get_secret_value()),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account could not be created with those details") from None
    return _create_login_response(request, response, db, user, settings, "auth.registered")


@router.post(
    "/login",
    response_model=AuthResponse,
    dependencies=[Depends(_login_rate_limit), Depends(require_anonymous_csrf)],
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    """Authenticate using a generic failure response and issue a revocable session."""
    user = db.scalar(select(User).where(User.email == str(payload.email).strip().lower()))
    password = payload.password.get_secret_value()
    candidate_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    valid_password = verify_password(password, candidate_hash)
    if user is None or not user.is_active or not valid_password:
        record_security_event(db, request, settings, "auth.login_failed")
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if password_hash_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return _create_login_response(request, response, db, user, settings, "auth.login_succeeded")


@router.get("/me", response_model=UserResponse)
def current_user(context: AuthenticatedContext = Depends(get_authenticated_context)) -> UserResponse:
    """Return only the identity attached to the caller's active session."""
    return UserResponse.from_user(context.user)


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    context: AuthenticatedContext = Depends(require_authenticated_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Revoke the current session so its token can no longer authenticate."""
    context.session.revoked_at = utcnow()
    record_security_event(db, request, settings, "auth.logout", user_id=context.user.id)
    db.commit()
    _delete_auth_cookies(response, settings)
    response.status_code = 204
    return response


@router.post("/logout-all", status_code=204)
def logout_all(
    request: Request,
    response: Response,
    context: AuthenticatedContext = Depends(require_authenticated_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Revoke all active sessions owned by the current user."""
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == context.user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    record_security_event(db, request, settings, "auth.logout_all", user_id=context.user.id)
    db.commit()
    _delete_auth_cookies(response, settings)
    response.status_code = 204
    return response


def _delete_auth_cookies(response: Response, settings: Settings) -> None:
    options = {"path": "/", "secure": settings.app_env == "production", "samesite": "lax"}
    response.delete_cookie(key=SESSION_COOKIE, httponly=True, **options)
    response.delete_cookie(key=CSRF_COOKIE, httponly=False, **options)
