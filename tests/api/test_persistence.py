from __future__ import annotations

from fastapi.testclient import TestClient


def _register(client: TestClient, email: str) -> str:
    csrf = client.get("/auth/csrf")
    assert csrf.status_code == 200
    token = csrf.json()["csrf_token"]
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "SafePassword-For-Tests-123"},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 201, response.text
    return response.json()["csrf_token"]


def test_academic_profile_is_persisted_and_can_be_deleted(client: TestClient) -> None:
    token = _register(client, "profile-owner@example.com")

    missing = client.get("/profile/me")
    assert missing.status_code == 404

    payload = {
        "qualification": " ICS ",
        "ssc_percent": 83.5,
        "hssc_percent": 78,
        "subjects": ["Mathematics", " Physics ", "mathematics"],
        "subject_percentages": {"Mathematics": 88, "Physics": 77},
        "equivalency_status": "not_required",
    }
    saved = client.put("/profile/me", json=payload, headers={"X-CSRF-Token": token})
    assert saved.status_code == 200, saved.text
    data = saved.json()
    assert data["qualification"] == "ICS"
    assert data["subjects"] == ["Mathematics", "Physics"]
    assert data["ssc_percent"] == 83.5

    reloaded = client.get("/profile/me")
    assert reloaded.status_code == 200
    assert reloaded.json()["subject_percentages"]["Mathematics"] == 88
    assert reloaded.headers["cache-control"] == "no-store"

    deleted = client.delete("/profile/me", headers={"X-CSRF-Token": token})
    assert deleted.status_code == 204
    assert client.get("/profile/me").status_code == 404


def test_profiles_are_isolated_between_accounts(client: TestClient) -> None:
    token_one = _register(client, "first-owner@example.com")
    saved = client.put(
        "/profile/me",
        json={"qualification": "FSc", "ssc_percent": 70},
        headers={"X-CSRF-Token": token_one},
    )
    assert saved.status_code == 200

    _register(client, "second-owner@example.com")
    assert client.get("/profile/me").status_code == 404


def test_conversation_messages_persist_and_foreign_conversation_id_is_not_found(client: TestClient) -> None:
    token_one = _register(client, "conversation-owner@example.com")
    created = client.post(
        "/conversations",
        json={"title": "Admissions options"},
        headers={"X-CSRF-Token": token_one},
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]

    added = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "What other universities should I consider?"},
        headers={"X-CSRF-Token": token_one},
    )
    assert added.status_code == 201, added.text
    assert added.json()["role"] == "user"

    details = client.get(f"/conversations/{conversation_id}")
    assert details.status_code == 200
    assert details.json()["messages"][0]["content"] == "What other universities should I consider?"
    assert details.json()["messages"][0]["citations"] == []

    listed = client.get("/conversations")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == conversation_id

    _register(client, "other-conversation-user@example.com")
    assert client.get(f"/conversations/{conversation_id}").status_code == 404
    assert client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "I should not be able to add this."},
        headers={"X-CSRF-Token": client.cookies.get("edupath_csrf")},
    ).status_code == 404


def test_profile_percentages_are_validated(client: TestClient) -> None:
    token = _register(client, "invalid-profile@example.com")
    response = client.put(
        "/profile/me",
        json={"ssc_percent": 101},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 422
