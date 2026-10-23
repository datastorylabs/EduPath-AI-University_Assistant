"""Registration, login, logout, CSRF bootstrap, and current-user endpoints."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.app.database import get_db
from backend.app.models.conversation import Conversation, ConversationMessage
from backend.app.models.session import AuthSession
from backend.app.models.student_profile import StudentProfile
from backend.app.models.user import User
from backend.app.schemas import AuthResponse, DeleteAccountRequest, LoginRequest, RegisterRequest, UserResponse
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


def _account_delete_rate_limit(request: Request) -> None:
    # Bound repeated destructive-password checks, including in local demos.
    enforce_rate_limit(request, "account-delete", 5)


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
def get_csrf_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Bootstrap CSRF for anonymous clients or preserve/rotate a live session token."""
    raw_session = request.cookies.get(SESSION_COOKIE)
    if raw_session:
        auth_session = db.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == token_digest(raw_session),
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > utcnow(),
            )
        )
        if auth_session is not None:
            existing_csrf = request.cookies.get(CSRF_COOKIE, "")
            if existing_csrf and secrets.compare_digest(
                token_digest(existing_csrf), auth_session.csrf_token_hash
            ):
                # Re-bootstrap without invalidating the live session's current token.
                return {"csrf_token": existing_csrf}
            csrf_token = secrets.token_urlsafe(32)
            auth_session.csrf_token_hash = token_digest(csrf_token)
            db.commit()
        else:
            csrf_token = secrets.token_urlsafe(32)
    else:
        csrf_token = secrets.token_urlsafe(32)

    response.set_cookie(
        key=CSRF_COOKIE,
        value=csrf_token,
        max_age=settings.session_ttl_hours * 3600 if raw_session else 1800,
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


@router.delete(
    "/account",
    status_code=204,
    dependencies=[Depends(_account_delete_rate_limit)],
    summary="Permanently delete the signed-in user's account and saved data",
)
def delete_account(
    payload: DeleteAccountRequest,
    request: Request,
    response: Response,
    context: AuthenticatedContext = Depends(require_authenticated_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Delete account-owned profile/history only after CSRF and password re-confirmation."""
    user_id = context.user.id
    if not verify_password(payload.password.get_secret_value(), context.user.password_hash):
        record_security_event(db, request, settings, "auth.account_delete_failed", user_id=user_id)
        db.commit()
        raise HTTPException(status_code=403, detail="Password confirmation failed")

    # Delete child rows explicitly in one transaction for predictable behavior
    # across SQLite demos and PostgreSQL deployments.
    owned_conversations = select(Conversation.id).where(Conversation.user_id == user_id)
    db.execute(delete(ConversationMessage).where(ConversationMessage.conversation_id.in_(owned_conversations)))
    db.execute(delete(Conversation).where(Conversation.user_id == user_id))
    db.execute(delete(StudentProfile).where(StudentProfile.user_id == user_id))
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))

    # Keep a minimal deletion event without an account identifier. Older audit
    # records have user_id set to NULL through their ON DELETE SET NULL FK.
    record_security_event(db, request, settings, "auth.account_deleted")
    deleted = db.execute(delete(User).where(User.id == user_id))
    if deleted.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=401, detail="Authentication required")
    db.commit()

    _delete_auth_cookies(response, settings)
    response.status_code = 204
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def _delete_auth_cookies(response: Response, settings: Settings) -> None:
    options = {"path": "/", "secure": settings.app_env == "production", "samesite": "lax"}
    response.delete_cookie(key=SESSION_COOKIE, httponly=True, **options)
    response.delete_cookie(key=CSRF_COOKIE, httponly=False, **options)
