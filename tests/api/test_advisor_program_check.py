from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _register(client: TestClient, email: str) -> str:
    csrf = client.get("/auth/csrf")
    assert csrf.status_code == 200
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "SafePassword-For-Tests-123"},
        headers={"X-CSRF-Token": csrf.json()["csrf_token"]},
    )
    assert response.status_code == 201, response.text
    return response.json()["csrf_token"]


def _create_profile(client: TestClient, token: str) -> None:
    response = client.put(
        "/profile/me",
        json={
            "qualification": "ICS",
            "ssc_percent": 84,
            "hssc_percent": 79,
            "subjects": ["Mathematics", "Physics", "Computer Science"],
            "subject_percentages": {"Mathematics": 85, "Physics": 78},
            "equivalency_status": "not_required",
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200, response.text


def test_profile_program_check_is_rules_based_cited_and_persisted(client: TestClient) -> None:
    token = _register(client, "program-check@example.com")
    _create_profile(client, token)
    conversation_response = client.post(
        "/conversations",
        json={"title": "My program fit"},
        headers={"X-CSRF-Token": token},
    )
    assert conversation_response.status_code == 201, conversation_response.text
    conversation_id = conversation_response.json()["id"]

    response = client.post(
        f"/conversations/{conversation_id}/program-check",
        json={"mode": "find_matches"},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_rules"] == 8
    assert payload["eligible_count"] > 0
    assert payload["assistant_message"]["role"] == "assistant"
    assert payload["assistant_message"]["citations"]
    stored = json.loads(payload["assistant_message"]["content"])
    assert stored["type"] == "profile_program_check"
    assert stored["mode"] == "find_matches"
    assert len(stored["results"]) == 8
    assert all(result["sources"] for result in stored["results"])
    assert all(source["verification_status"] == "verified" for source in payload["assistant_message"]["citations"])

    detail = client.get(f"/conversations/{conversation_id}")
    assert detail.status_code == 200
    assert [message["role"] for message in detail.json()["messages"]] == ["user", "assistant"]


def test_program_check_requires_a_saved_profile(client: TestClient) -> None:
    token = _register(client, "need-profile@example.com")
    created = client.post(
        "/conversations",
        json={"title": "Profile first"},
        headers={"X-CSRF-Token": token},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    response = client.post(
        f"/conversations/{conversation_id}/program-check",
        json={"mode": "find_matches"},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 409
    detail = client.get(f"/conversations/{conversation_id}").json()
    assert detail["messages"] == []


def test_program_check_is_owner_scoped_and_csrf_protected(client: TestClient) -> None:
    owner_token = _register(client, "program-owner@example.com")
    _create_profile(client, owner_token)
    conversation = client.post(
        "/conversations",
        json={"title": "Private review"},
        headers={"X-CSRF-Token": owner_token},
    )
    conversation_id = conversation.json()["id"]

    _register(client, "not-program-owner@example.com")
    foreign = client.post(
        f"/conversations/{conversation_id}/program-check",
        json={"mode": "find_matches"},
        headers={"X-CSRF-Token": client.cookies.get("edupath_csrf")},
    )
    assert foreign.status_code == 404

    no_csrf = client.post(
        f"/conversations/{conversation_id}/program-check",
        json={"mode": "find_matches"},
    )
    assert no_csrf.status_code in {401, 403}
