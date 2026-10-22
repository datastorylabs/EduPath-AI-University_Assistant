"""Deterministic, fail-closed eligibility evaluation for versioned admission rules.

This service intentionally refuses to infer a rule from missing or unverified data.
It evaluates only the explicitly structured rule fields supplied by the data layer.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Mapping


class EligibilityStatus(str, Enum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class RequirementResult:
    requirement: str
    status: str
    explanation: str


@dataclass(frozen=True)
class EligibilityResult:
    status: EligibilityStatus
    university_id: str
    program_id: str
    rule_version: str | None
    checks: tuple[RequirementResult, ...]
    sources: tuple[str, ...]
    disclaimer: str = "Minimum eligibility is not a guarantee of competitive merit or admission."

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


def evaluate_eligibility(
    profile: Mapping[str, Any],
    rule: Mapping[str, Any] | None,
) -> EligibilityResult:
    """Evaluate marks and required subjects; missing/unverified rules fail closed.

    Supported rule fields:
      verified (bool), university_id, program_id, version, sources,
      minimum_ssc_percent, minimum_hssc_percent, required_subjects,
      accepted_qualifications, cycle.
    Profile fields:
      ssc_percent, hssc_percent, subjects (list[str]), qualification, cycle.
    """
    empty = EligibilityResult(
        EligibilityStatus.INDETERMINATE,
        str((rule or {}).get("university_id", "unknown")),
        str((rule or {}).get("program_id", "unknown")),
        (rule or {}).get("version"),
        (RequirementResult("rule", "unknown", "No applicable verified rule was supplied."),),
        tuple((rule or {}).get("sources", ())),
    )
    if not rule or rule.get("verified") is not True:
        return empty

    university_id = str(rule.get("university_id", "unknown"))
    program_id = str(rule.get("program_id", "unknown"))
    version = rule.get("version")
    sources = tuple(str(s) for s in rule.get("sources", ()) if s)
    checks: list[RequirementResult] = []
    missing = False
    failed = False

    rule_cycle = rule.get("cycle")
    profile_cycle = profile.get("cycle")
    if rule_cycle and profile_cycle and rule_cycle != profile_cycle:
        return EligibilityResult(
            EligibilityStatus.INDETERMINATE, university_id, program_id, version,
            (RequirementResult("admission_cycle", "unknown",
              f"Rule applies to {rule_cycle}; profile specifies {profile_cycle}."),), sources,
        )
    if rule_cycle and not profile_cycle:
        missing = True
        checks.append(RequirementResult("admission_cycle", "unknown", "Admission cycle is required."))

    qualification = profile.get("qualification")
    accepted = rule.get("accepted_qualifications")
    if accepted:
        if not qualification:
            missing = True
            checks.append(RequirementResult("qualification", "unknown", "Academic qualification is missing."))
        elif str(qualification).casefold() not in {str(q).casefold() for q in accepted}:
            failed = True
            checks.append(RequirementResult("qualification", "fail",
                f"Qualification {qualification!r} is not in the rule's accepted qualification list."))
        else:
            checks.append(RequirementResult("qualification", "pass", "Qualification matches a listed accepted option."))

    for field, label in (("minimum_ssc_percent", "SSC percentage"), ("minimum_hssc_percent", "HSSC percentage")):
        threshold = rule.get(field)
        if threshold is None:
            continue
        value = profile.get("ssc_percent" if field == "minimum_ssc_percent" else "hssc_percent")
        if value is None:
            missing = True
            checks.append(RequirementResult(label, "unknown", f"{label} is required to evaluate the published minimum."))
        else:
            try:
                numeric = float(value)
                limit = float(threshold)
            except (TypeError, ValueError):
                missing = True
                checks.append(RequirementResult(label, "unknown", f"{label} must be a valid number."))
                continue
            if not 0 <= numeric <= 100:
                missing = True
                checks.append(RequirementResult(label, "unknown", f"{label} must be between 0 and 100."))
            elif numeric < limit:
                failed = True
                checks.append(RequirementResult(label, "fail", f"{numeric:g}% is below the published minimum of {limit:g}%."))
            else:
                checks.append(RequirementResult(label, "pass", f"{numeric:g}% meets the published minimum of {limit:g}%."))

    required_subjects = {str(s).strip().casefold() for s in rule.get("required_subjects", ())}
    if required_subjects:
        supplied = profile.get("subjects")
        if supplied is None:
            missing = True
            checks.append(RequirementResult("subjects", "unknown", "Subject list is missing."))
        else:
            actual = {str(s).strip().casefold() for s in supplied}
            absent = sorted(required_subjects - actual)
            if absent:
                failed = True
                checks.append(RequirementResult("subjects", "fail", "Missing required subjects: " + ", ".join(absent) + "."))
            else:
                checks.append(RequirementResult("subjects", "pass", "All explicitly required subjects are present."))

    if not checks:
        checks.append(RequirementResult("rule", "unknown", "No supported deterministic checks are configured."))
        missing = True

    status = EligibilityStatus.INELIGIBLE if failed else (
        EligibilityStatus.INDETERMINATE if missing else EligibilityStatus.ELIGIBLE
    )
    return EligibilityResult(status, university_id, program_id, version, tuple(checks), sources)
