from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from backend.app.models.audit_event import SecurityAuditEvent
from backend.app.models.session import AuthSession
from backend.app.models.user import User
from backend.app.security import CSRF_COOKIE, SESSION_COOKIE, assert_resource_owner, token_digest, utcnow


def csrf(client) -> str:
    response = client.get("/auth/csrf")
    assert response.status_code == 200
    token = response.json()["csrf_token"]
    assert client.cookies.get(CSRF_COOKIE) == token
    return token


def register(client, email="student@example.com", password="Correct-Horse-12!"):
    token = csrf(client)
    return client.post("/auth/register", headers={"X-CSRF-Token": token},
                       json={"email": email, "password": password})


def test_registration_hashes_password_and_issues_opaque_session(client):
    response = register(client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == "student@example.com"
    assert body["csrf_token"] == client.cookies.get(CSRF_COOKIE)
    session_token = client.cookies.get(SESSION_COOKIE)
    assert session_token and "password" not in body
    assert response.headers["cache-control"] == "no-store"
    session_header = next(h.lower() for h in response.headers.get_list("set-cookie") if SESSION_COOKIE in h)
    assert "httponly" in session_header and "samesite=lax" in session_header
    with client.app.state.testing_session_factory() as db:
        user = db.scalar(select(User).where(User.email == "student@example.com"))
        assert user.password_hash.startswith("$argon2id$") and user.password_hash != "Correct-Horse-12!"
        session = db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
        assert session.token_hash == token_digest(session_token) and session.token_hash != session_token
        assert session.csrf_token_hash == token_digest(body["csrf_token"])
        events = db.scalars(select(SecurityAuditEvent)).all()
        assert any(event.event_type == "auth.registered" for event in events)
        assert all(event.ip_hash != "testclient" for event in events)


def test_csrf_required_for_registration(client):
    response = client.post("/auth/register", json={"email": "student@example.com", "password": "Correct-Horse-12!"})
    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF validation failed"


def test_csrf_cookie_and_header_must_match(client):
    csrf(client)
    response = client.post("/auth/register", headers={"X-CSRF-Token": "attacker-controlled-token"},
                           json={"email": "student@example.com", "password": "Correct-Horse-12!"})
    assert response.status_code == 403


def test_invalid_short_password_error_does_not_echo_password(client):
    token = csrf(client)
    response = client.post("/auth/register", headers={"X-CSRF-Token": token},
                           json={"email": "student@example.com", "password": "abc"})
    assert response.status_code == 422
    assert "abc" not in response.text and '"input"' not in response.text


def test_login_failure_is_generic_and_audited(client):
    assert register(client).status_code == 201
    response1 = client.post("/auth/login", headers={"X-CSRF-Token": csrf(client)},
                            json={"email": "nobody@example.com", "password": "bad-password"})
    response2 = client.post("/auth/login", headers={"X-CSRF-Token": csrf(client)},
                            json={"email": "student@example.com", "password": "Wrong-password-12!"})
    assert response1.status_code == response2.status_code == 401
    assert response1.json() == response2.json() == {"detail": "Invalid email or password"}
    with client.app.state.testing_session_factory() as db:
        types = [e.event_type for e in db.scalars(select(SecurityAuditEvent)).all()]
        assert types.count("auth.login_failed") == 2


def test_current_user_and_logout_revoke_the_session(client):
    response = register(client)
    assert response.status_code == 201
    raw_session = client.cookies.get(SESSION_COOKIE)
    assert client.get("/auth/me").json()["email"] == "student@example.com"
    logout = client.post("/auth/logout", headers={"X-CSRF-Token": response.json()["csrf_token"]})
    assert logout.status_code == 204
    assert client.get("/auth/me", cookies={SESSION_COOKIE: raw_session}).status_code == 401
    with client.app.state.testing_session_factory() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(raw_session)))
        assert session.revoked_at is not None


def test_logout_requires_valid_csrf_token(client):
    assert register(client).status_code == 201
    assert client.post("/auth/logout", headers={"X-CSRF-Token": "invalid-token"}).status_code == 403


def test_expired_session_is_rejected(client):
    assert register(client).status_code == 201
    raw_session = client.cookies.get(SESSION_COOKIE)
    with client.app.state.testing_session_factory() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(raw_session)))
        session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    client.cookies.set(SESSION_COOKIE, raw_session)
    assert client.get("/auth/me").status_code == 401


def test_inactive_user_session_is_revoked(client):
    assert register(client).status_code == 201
    raw_session = client.cookies.get(SESSION_COOKIE)
    with client.app.state.testing_session_factory() as db:
        user = db.scalar(select(User).where(User.email == "student@example.com"))
        user.is_active = False
        db.commit()
    client.cookies.set(SESSION_COOKIE, raw_session)
    assert client.get("/auth/me").status_code == 401
    with client.app.state.testing_session_factory() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(raw_session)))
        assert session.revoked_at is not None


def test_logout_all_revokes_all_sessions_for_user(client):
    first = register(client)
    first_token = client.cookies.get(SESSION_COOKIE)
    second = client.post("/auth/login", headers={"X-CSRF-Token": csrf(client)},
                         json={"email": "student@example.com", "password": "Correct-Horse-12!"})
    second_token = client.cookies.get(SESSION_COOKIE)
    assert second.status_code == 200 and first_token != second_token
    assert client.post("/auth/logout-all", headers={"X-CSRF-Token": second.json()["csrf_token"]}).status_code == 204
    client.cookies.set(SESSION_COOKIE, first_token)
    assert client.get("/auth/me").status_code == 401
    client.cookies.set(SESSION_COOKIE, second_token)
    assert client.get("/auth/me").status_code == 401


def test_auth_rate_limit_returns_retry_after(client):
    token = csrf(client)
    for _ in range(5):
        assert client.post("/auth/login", headers={"X-CSRF-Token": token},
                           json={"email": "nobody@example.com", "password": "not-the-password"}).status_code == 401
    limited = client.post("/auth/login", headers={"X-CSRF-Token": token},
                          json={"email": "nobody@example.com", "password": "not-the-password"})
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) >= 1


def test_cross_user_resource_owner_check_returns_not_found(client):
    assert register(client).status_code == 201
    with client.app.state.testing_session_factory() as db:
        user = db.scalar(select(User).where(User.email == "student@example.com"))
        assert_resource_owner(user.id, user)
        try:
            assert_resource_owner(uuid4(), user)
        except HTTPException as exc:
            assert exc.status_code == 404 and exc.detail == "Resource not found"
        else:
            raise AssertionError("cross-user resource must be rejected")


def test_security_headers_are_set(client):
    response = client.get("/auth/csrf")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
