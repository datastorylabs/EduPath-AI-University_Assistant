from datetime import date

from backend.app.services.admissions_rules import EligibilityStatus, evaluate_eligibility
from backend.app.services.admissions_sources import is_stale, validate_source_record


def rule(**overrides):
    data = {
        "verified": True, "university_id": "nust", "program_id": "bs-ai",
        "version": "2026-2027.1", "cycle": "2026-2027",
        "minimum_ssc_percent": 60, "minimum_hssc_percent": 60,
        "required_subjects": ["mathematics"], "accepted_qualifications": ["ICS"],
        "sources": ["https://nust.edu.pk/admissions/undergraduates/eligibility-criteria-for-ug-programmes/"],
    }
    data.update(overrides)
    return data


def profile(**overrides):
    data = {"ssc_percent": 60, "hssc_percent": 60, "subjects": ["Mathematics", "Physics", "Computer Science"],
            "qualification": "ICS", "cycle": "2026-2027"}
    data.update(overrides)
    return data


def test_exact_boundary_percentages_are_eligible():
    assert evaluate_eligibility(profile(), rule()).status is EligibilityStatus.ELIGIBLE


def test_below_minimum_is_ineligible():
    result = evaluate_eligibility(profile(hssc_percent=59.99), rule())
    assert result.status is EligibilityStatus.INELIGIBLE
    assert any("below the published minimum" in check.explanation for check in result.checks)


def test_missing_marks_is_indeterminate_not_ineligible():
    assert evaluate_eligibility(profile(hssc_percent=None), rule()).status is EligibilityStatus.INDETERMINATE


def test_missing_subject_is_indeterminate():
    assert evaluate_eligibility(profile(subjects=None), rule()).status is EligibilityStatus.INDETERMINATE


def test_missing_required_subject_is_ineligible():
    result = evaluate_eligibility(profile(subjects=["Physics", "Computer Science"]), rule())
    assert result.status is EligibilityStatus.INELIGIBLE
    assert "mathematics" in " ".join(c.explanation for c in result.checks)


def test_unverified_rule_fails_closed():
    assert evaluate_eligibility(profile(), rule(verified=False)).status is EligibilityStatus.INDETERMINATE


def test_conflicting_cycle_is_indeterminate():
    assert evaluate_eligibility(profile(cycle="2025-2026"), rule()).status is EligibilityStatus.INDETERMINATE


def test_missing_qualification_is_indeterminate():
    assert evaluate_eligibility(profile(qualification=None), rule()).status is EligibilityStatus.INDETERMINATE


def test_wrong_qualification_is_ineligible():
    assert evaluate_eligibility(profile(qualification="FA"), rule()).status is EligibilityStatus.INELIGIBLE


def test_bad_percent_is_indeterminate():
    assert evaluate_eligibility(profile(ssc_percent=130), rule()).status is EligibilityStatus.INDETERMINATE


def test_source_record_validation_and_staleness():
    source = {"source_id":"x","university_id":"nust","title":"Official criteria",
              "url":"https://nust.edu.pk/","source_type":"official_policy",
              "admission_cycle":"2026-2027","last_verified":"2026-10-01",
              "verification_status":"verified"}
    assert validate_source_record(source) == []
    assert not is_stale(source, today=date(2026,10,22), max_age_days=365)
    assert is_stale({**source, "verification_status":"unverified"}, today=date(2026,10,22))
