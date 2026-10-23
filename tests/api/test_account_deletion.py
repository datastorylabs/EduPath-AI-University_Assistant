from __future__ import annotations

from sqlalchemy import func, select

from backend.app.models.audit_event import SecurityAuditEvent
from backend.app.models.conversation import Conversation, ConversationMessage
from backend.app.models.session import AuthSession
from backend.app.models.student_profile import StudentProfile
from backend.app.models.user import User


PASSWORD = "SafePassword-For-Tests-123"


def register(client, email: str) -> str:
    csrf = client.get("/auth/csrf")
    assert csrf.status_code == 200
    token = csrf.json()["csrf_token"]
    response = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 201, response.text
    return response.json()["csrf_token"]


def test_account_deletion_requires_csrf_and_password_then_removes_owned_data(client) -> None:
    token = register(client, "delete-me@example.com")
    profile = client.put(
        "/profile/me",
        json={
            "qualification": "FSc Pre-Engineering",
            "ssc_percent": 82,
            "hssc_percent": 78,
            "subjects": ["Mathematics", "Physics"],
            "subject_percentages": {"Mathematics": 85},
            "equivalency_status": "not_required",
        },
        headers={"X-CSRF-Token": token},
    )
    assert profile.status_code == 200, profile.text

    created = client.post("/conversations", json={"title": "Private admissions review"},
                          headers={"X-CSRF-Token": token})
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]
    message = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "A private academic question"},
        headers={"X-CSRF-Token": token},
    )
    assert message.status_code == 201

    no_csrf = client.request("DELETE", "/auth/account", json={"password": PASSWORD})
    assert no_csrf.status_code == 403

    wrong_password = client.request(
        "DELETE", "/auth/account", json={"password": "Wrong-Password-123"},
        headers={"X-CSRF-Token": token},
    )
    assert wrong_password.status_code == 403
    assert wrong_password.json() == {"detail": "Password confirmation failed"}
    assert client.get("/auth/me").status_code == 200
    assert client.get("/profile/me").status_code == 200
    assert client.get(f"/conversations/{conversation_id}").status_code == 200

    deleted = client.request(
        "DELETE", "/auth/account", json={"password": PASSWORD},
        headers={"X-CSRF-Token": token},
    )
    assert deleted.status_code == 204
    assert deleted.headers["cache-control"] == "no-store"
    assert client.get("/auth/me").status_code == 401
    assert client.get("/profile/me").status_code == 401
    assert client.get(f"/conversations/{conversation_id}").status_code == 401

    with client.app.state.testing_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 0
        assert db.scalar(select(func.count()).select_from(StudentProfile)) == 0
        assert db.scalar(select(func.count()).select_from(Conversation)) == 0
        assert db.scalar(select(func.count()).select_from(ConversationMessage)) == 0
        events = db.scalars(select(SecurityAuditEvent)).all()
        assert any(e.event_type == "auth.account_deleted" and e.user_id is None for e in events)
        assert any(e.event_type == "auth.account_delete_failed" and e.user_id is None for e in events)


def test_account_deletion_requires_an_authenticated_user(client) -> None:
    csrf = client.get("/auth/csrf").json()["csrf_token"]
    response = client.request("DELETE", "/auth/account", json={"password": PASSWORD},
                              headers={"X-CSRF-Token": csrf})
    assert response.status_code == 401
