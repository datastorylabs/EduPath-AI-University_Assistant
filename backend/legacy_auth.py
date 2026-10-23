"""Server-side sign-in for the original Streamlit multipage application."""
from __future__ import annotations

import hashlib
import hmac
import re
import threading
import time

import streamlit as st
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.app.config import get_settings
from backend.app.database import SessionLocal
from backend.app.models.audit_event import SecurityAuditEvent
from backend.app.models.conversation import Conversation, ConversationMessage
from backend.app.models.legacy_application_state import LegacyApplicationState
from backend.app.models.session import AuthSession
from backend.app.models.student_profile import StudentProfile
from backend.app.models.user import User
from backend.app.security import issue_session, token_digest, utcnow
from backend.app.services.passwords import hash_password, verify_password
from backend.private_documents import delete_user_private_documents

_DUMMY_HASH = hash_password("edupath-never-used-dummy-password-for-timing")
_ATTEMPTS: dict[str, tuple[int, int]] = {}
_ATTEMPTS_LOCK = threading.Lock()
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _client_ip() -> str:
    try:
        return str(getattr(st.context, "ip_address", None) or "unknown")
    except Exception:
        return "unknown"


def _rate_key(scope: str, email: str) -> str:
    settings = get_settings()
    secret = settings.secret_key.get_secret_value().encode("utf-8") or b"edupath-development-only-rate-key"
    raw = f"{scope}|{email.casefold()}|{_client_ip()}".encode("utf-8", errors="ignore")
    return hmac.new(secret, raw, hashlib.sha256).hexdigest()


def _rate_allowed(scope: str, email: str, limit: int) -> tuple[bool, str | None]:
    """Use shared TLS Redis limits in production and bounded in-memory limits locally."""
    settings = get_settings()
    key = f"edupath:streamlit-auth:{scope}:{_rate_key(scope, email)}"
    window = max(1, settings.auth_rate_window_seconds)
    if settings.app_env == "production":
        if not settings.redis_url or not settings.redis_url.startswith("rediss://"):
            return False, "Authentication is temporarily unavailable."
        try:
            from redis import Redis
            client = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
            count = int(client.eval(
                "local n=redis.call('INCR',KEYS[1]); "
                "if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n",
                1, key, window,
            ))
        except Exception:
            return False, "Authentication is temporarily unavailable."
        return (count <= limit, None if count <= limit else "Too many attempts. Please try again after a minute.")

    now = int(time.time())
    start = now - (now % window)
    with _ATTEMPTS_LOCK:
        if len(_ATTEMPTS) > 10_000:
            for old_key, (old_start, _) in list(_ATTEMPTS.items()):
                if old_start < start:
                    _ATTEMPTS.pop(old_key, None)
        entry_start, count = _ATTEMPTS.get(key, (start, 0))
        if entry_start != start:
            entry_start, count = start, 0
        count += 1
        _ATTEMPTS[key] = (entry_start, count)
    return (count <= limit, None if count <= limit else "Too many attempts. Please try again after a minute.")


def _audit(db, event_type: str, user_id=None) -> None:
    db.add(SecurityAuditEvent(event_type=event_type, user_id=user_id))


def _clear_application_keys() -> None:
    """Called before app widgets are rendered, for identity change/session expiry."""
    for key in list(st.session_state.keys()):
        if not str(key).startswith("_edupath_"):
            try:
                del st.session_state[key]
            except Exception:
                pass
    st.session_state.pop("_edupath_loaded_user_id", None)
    st.session_state.pop("_edupath_storage_error", None)


def _set_identity(user: User, token: str, notice: str) -> None:
    # Do not delete just-submitted login widgets mid-run; the next authenticated
    # run restores a fresh, owner-scoped snapshot before any app widgets render.
    st.session_state.pop("_edupath_loaded_user_id", None)
    st.session_state.pop("_edupath_storage_error", None)
    st.session_state["_edupath_user_id"] = str(user.id)
    st.session_state["_edupath_email"] = user.email
    st.session_state["_edupath_session_token"] = token
    st.session_state["_edupath_auth_notice"] = notice
    st.rerun()


def _create_account(email: str, password: str) -> tuple[User | None, str | None]:
    email = email.strip().casefold()
    if len(email) > 320 or not _EMAIL_RE.fullmatch(email):
        return None, "Enter a valid email address."
    if len(password) < 12 or len(password) > 128:
        return None, "Use a password between 12 and 128 characters."
    allowed, message = _rate_allowed("register", email, get_settings().register_rate_limit)
    if not allowed:
        return None, message
    with SessionLocal() as db:
        try:
            user = User(email=email, password_hash=hash_password(password))
            db.add(user)
            db.flush()
            _audit(db, "streamlit.auth.registered", user_id=user.id)
            _session, raw_token, _csrf = issue_session(db, user, get_settings())
            db.commit()
            db.refresh(user)
            return user, raw_token
        except IntegrityError:
            db.rollback()
            return None, "An account could not be created with those details."
        except SQLAlchemyError:
            db.rollback()
            return None, "The account store is unavailable. Check database setup and migrations."


def _sign_in(email: str, password: str) -> tuple[User | None, str | None]:
    email = email.strip().casefold()
    allowed, message = _rate_allowed("login", email, get_settings().login_rate_limit)
    if not allowed:
        return None, message
    with SessionLocal() as db:
        try:
            user = db.scalar(select(User).where(User.email == email))
            candidate_hash = user.password_hash if user is not None else _DUMMY_HASH
            valid = verify_password(password, candidate_hash)
            if user is None or not user.is_active or not valid:
                _audit(db, "streamlit.auth.login_failed")
                db.commit()
                return None, "Invalid email or password."
            _audit(db, "streamlit.auth.login_succeeded", user_id=user.id)
            _session, raw_token, _csrf = issue_session(db, user, get_settings())
            db.commit()
            db.refresh(user)
            return user, raw_token
        except SQLAlchemyError:
            db.rollback()
            return None, "Authentication storage is unavailable. Check database setup and migrations."


def _render_auth_screen() -> None:
    st.markdown(
        """
        <div style="max-width:720px;margin:2.5rem auto 1.25rem auto;">
          <div style="color:#4F46E5;font-weight:700;letter-spacing:.08em;">EDUPATH AI</div>
          <h1 style="font-size:2.4rem;line-height:1.15;color:#1E1B34;">Your university journey, simplified.</h1>
          <p style="color:#5B5876;font-size:1.05rem;">Sign in to continue with your saved academic profile and admissions history.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    notice = st.session_state.pop("_edupath_auth_notice", None)
    if notice:
        st.info(notice)
    login_tab, register_tab = st.tabs(["Sign in", "Create account"])
    with login_tab:
        with st.form("edupath_streamlit_signin"):
            email = st.text_input("Email address", max_chars=320, key="edupath_login_email").strip().casefold()
            password = st.text_input("Password", type="password", max_chars=128, key="edupath_login_password")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if submitted:
            user, token = _sign_in(email, password)
            if user is not None and token:
                _set_identity(user, token, "Signed in successfully.")
            else:
                st.error(token or "Authentication failed.")
    with register_tab:
        with st.form("edupath_streamlit_register"):
            email = st.text_input("Email address", max_chars=320, key="edupath_register_email").strip().casefold()
            password = st.text_input("Password", type="password", max_chars=128, key="edupath_register_password")
            confirm = st.text_input("Confirm password", type="password", max_chars=128, key="edupath_register_confirm")
            st.caption("Use 12–128 characters. Your password is never stored in plain text.")
            submitted = st.form_submit_button("Create account", type="primary", use_container_width=True)
        if submitted:
            if password != confirm:
                st.error("The passwords do not match.")
            else:
                user, token = _create_account(email, password)
                if user is not None and token:
                    _set_identity(user, token, "Your account has been created.")
                else:
                    st.error(token or "The account could not be created.")


def require_signed_in() -> None:
    """Validate the server-side session on every page run, or show sign-in."""
    raw_token = st.session_state.get("_edupath_session_token")
    if raw_token:
        try:
            with SessionLocal() as db:
                session = db.scalar(select(AuthSession).where(
                    AuthSession.token_hash == token_digest(str(raw_token)),
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > utcnow(),
                ))
                user = db.get(User, session.user_id) if session is not None else None
                if session is not None and user is not None and user.is_active:
                    st.session_state["_edupath_user_id"] = str(user.id)
                    st.session_state["_edupath_email"] = user.email
                    return
        except SQLAlchemyError:
            st.error("EduPath cannot reach its account database. Check the .env settings and apply Alembic migrations.")
            st.stop()
        _clear_application_keys()
        for key in ("_edupath_session_token", "_edupath_user_id", "_edupath_email"):
            st.session_state.pop(key, None)
        st.session_state["_edupath_auth_notice"] = "Your session expired or was revoked. Sign in again."
    _render_auth_screen()
    st.stop()


def sign_out_current_session() -> None:
    raw_token = st.session_state.get("_edupath_session_token")
    if raw_token:
        with SessionLocal() as db:
            session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(str(raw_token))))
            if session is not None and session.revoked_at is None:
                session.revoked_at = utcnow()
                _audit(db, "streamlit.auth.logout", user_id=session.user_id)
                db.commit()
    # Clear private application state immediately on sign-out, not only when a
    # different account signs in.
    _clear_application_keys()
    for key in ("_edupath_session_token", "_edupath_user_id", "_edupath_email", "_edupath_loaded_user_id", "_edupath_auth_notice"):
        st.session_state.pop(key, None)
    st.rerun()


def delete_current_account(password: str) -> tuple[bool, str]:
    raw_token = st.session_state.get("_edupath_session_token")
    if not raw_token:
        return False, "Sign in again before deleting the account."
    with SessionLocal() as db:
        session = db.scalar(select(AuthSession).where(
            AuthSession.token_hash == token_digest(str(raw_token)),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        ))
        user = db.get(User, session.user_id) if session is not None else None
        if user is None or not user.is_active:
            return False, "Your session expired. Sign in again."
        if not verify_password(password, user.password_hash):
            _audit(db, "streamlit.auth.account_delete_failed", user_id=user.id)
            db.commit()
            return False, "Password confirmation failed."

        # Remove private original uploads before deleting the account record.
        try:
            delete_user_private_documents(user.id)
        except OSError:
            db.rollback()
            return False, "Private document storage could not be cleaned up; the account was not deleted."
        owned_conversations = select(Conversation.id).where(Conversation.user_id == user.id)
        db.execute(delete(ConversationMessage).where(ConversationMessage.conversation_id.in_(owned_conversations)))
        db.execute(delete(Conversation).where(Conversation.user_id == user.id))
        db.execute(delete(StudentProfile).where(StudentProfile.user_id == user.id))
        db.execute(delete(LegacyApplicationState).where(LegacyApplicationState.user_id == user.id))
        db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        _audit(db, "streamlit.auth.account_deleted")
        db.execute(delete(User).where(User.id == user.id))
        db.commit()

    # Pop only the server-side identity; don't mutate current widget keys mid-run.
    for key in ("_edupath_session_token", "_edupath_user_id", "_edupath_email", "_edupath_loaded_user_id"):
        st.session_state.pop(key, None)
    return True, "Account and saved EduPath data deleted."


def render_account_controls() -> None:
    email = st.session_state.get("_edupath_email", "")
    with st.expander("Account & privacy", expanded=False):
        st.caption(f"Signed in as {email}")
        if st.button("Sign out", key="edupath_signout", use_container_width=True):
            sign_out_current_session()
        st.markdown("**Delete account permanently**")
        st.caption("This removes your saved profile, analyzed document fields/status, advisor history, private original uploads, and active sessions. Minimal account-unlinked security audit metadata may remain.")
        confirmed = st.checkbox("I understand this permanently deletes my account and saved data.", key="edupath_delete_confirm")
        password = st.text_input("Confirm current password", type="password", max_chars=128, key="edupath_delete_password")
        if st.button("Permanently delete account", disabled=not confirmed or not password, key="edupath_delete_account"):
            ok, message = delete_current_account(password)
            if ok:
                st.success(message)
                st.rerun()
            else:
                st.error(message)
