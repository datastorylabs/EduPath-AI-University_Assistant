from __future__ import annotations

from datetime import date

from backend.app.services.admissions_catalog import list_available_rules, list_universities
from backend.app.services.admissions_rules import EligibilityStatus, evaluate_eligibility


def test_api_catalog_reports_partial_research_without_claiming_everything_is_verified(client):
    response = client.get("/admissions/catalog")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_count"] >= 10
    assert payload["university_count"] >= 10
    assert payload["evaluable_rule_count"] == 8
    assert "not complete national coverage" in payload["coverage_notice"].lower()


def test_source_registry_distinguishes_discovery_entries_from_rules(client):
    payload = client.get("/admissions/universities").json()
    records = {item["university_id"]: item for item in payload["universities"]}
    assert records["comsats"]["verified_rule_count"] == 0
    assert records["comsats"]["research_complete"] is False
    assert records["fast-nuces"]["has_evaluable_rules"] is True
    assert records["fast-nuces"]["research_complete"] is False


def test_rules_api_returns_sources_and_all_checked_program_cycle_rules(client):
    all_rules = client.get("/admissions/rules").json()
    assert all_rules["count"] == 8
    assert all(rule["evaluation_available"] for rule in all_rules["rules"])
    assert all(rule["sources"] for rule in all_rules["rules"])

    verified = client.get("/admissions/rules?evaluable_only=true&university_id=nust&cycle=2026-2027")
    assert verified.status_code == 200
    assert len(verified.json()["rules"]) == 3
    assert {rule["program_id"] for rule in verified.json()["rules"]} == {
        "bs-artificial-intelligence", "bs-computer-science", "bs-data-science"
    }


def test_fast_ai_baseline_evaluation_is_deterministic_and_cycle_scoped(client):
    response = client.post("/admissions/evaluate", json={
        "university_id": "fast-nuces",
        "program_id": "bachelor-of-science-artificial-intelligence",
        "cycle": "2026",
        "profile": {
            "qualification": "ICS",
            "ssc_percent": 60,
            "hssc_percent": 50,
            "subjects": ["Mathematics", "Physics", "Computer Science"],
            "cycle": "2026",
        },
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == EligibilityStatus.ELIGIBLE.value
    assert payload["rule_availability"]["available"] is True
    assert payload["source_details"][0]["url"] == "https://nu.edu.pk/Admissions/EligibilityCriteria"


def test_foreign_qualification_without_ibcc_equivalence_is_not_confirmed(client):
    response = client.post("/admissions/evaluate", json={
        "university_id": "nust",
        "program_id": "bs-artificial-intelligence",
        "cycle": "2026-2027",
        "profile": {
            "qualification": "A Levels",
            "ssc_percent": 60,
            "hssc_percent": 60,
            "subjects": ["Mathematics", "Physics", "Chemistry"],
        },
    })
    assert response.status_code == 200
    assert response.json()["status"] == EligibilityStatus.INDETERMINATE.value
    assert any(check["requirement"] == "ibcc_equivalence" for check in response.json()["checks"])


def test_missing_program_cycle_rule_returns_indeterminate_with_a_reason_not_a_guess(client):
    response = client.post("/admissions/evaluate", json={
        "university_id": "fast-nuces",
        "program_id": "bachelor-of-science-computer-science",
        "cycle": "2027",
        "profile": {
            "qualification": "ICS",
            "ssc_percent": 80,
            "hssc_percent": 90,
            "subjects": ["Mathematics", "Physics", "Computer Science"],
        },
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == EligibilityStatus.INDETERMINATE.value
    assert payload["rule_availability"]["available"] is False
    assert "No program-specific" in payload["rule_availability"]["reason"]


def test_cycle_conflict_is_not_eligible(client):
    response = client.post("/admissions/evaluate", json={
        "university_id": "fast-nuces",
        "program_id": "bachelor-of-science-artificial-intelligence",
        "cycle": "2026",
        "profile": {
            "qualification": "ICS",
            "ssc_percent": 80,
            "hssc_percent": 90,
            "subjects": ["Mathematics"],
            "cycle": "2025",
        },
    })
    assert response.status_code == 200
    assert response.json()["status"] == EligibilityStatus.INDETERMINATE.value


def test_future_review_date_does_not_keep_expired_rule_evaluable():
    rules = list_available_rules(today=date(2028, 1, 1))
    assert rules
    assert not any(rule["evaluation_available"] for rule in rules)


def test_compare_endpoint_labels_uncovered_university_as_unknown_not_unsuitable(client):
    response = client.post("/admissions/compare", json={
        "program_family": "computing",
        "cycle": "2026-2027",
        "university_ids": ["nust", "fast-nuces"],
    })
    assert response.status_code == 200
    payload = response.json()
    assert [rule["university_id"] for rule in payload["rules"]] == ["nust", "nust", "nust"]
    assert payload["university_ids_without_verified_rule"] == ["fast-nuces"]
    assert "unknown" in payload["notice"].lower()

def test_current_registry_tracks_expired_punjab_phase_and_verified_nust_merit_source(client):
    sources = client.get("/admissions/sources").json()["sources"]
    pu_phase = next(source for source in sources if source["source_id"] == "pu-vacant-seats-phase2-2026-2027")
    nust_merit = next(source for source in sources if source["source_id"] == "nust-ug-merit-2026-2027")
    assert pu_phase["verification_status"] == "stale"
    assert nust_merit["verification_status"] == "verified"
