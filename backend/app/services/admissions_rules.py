"""Deterministic, fail-closed eligibility evaluation for sourced admissions rules."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import re
from typing import Any, Mapping


class EligibilityStatus(str, Enum):
    ELIGIBLE = "eligible"
    CONDITIONALLY_ELIGIBLE = "conditionally_eligible"
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


_SUBJECT_ALIASES = {
    "math": "mathematics",
    "maths": "mathematics",
    "mathematics": "mathematics",
    "physics": "physics",
    "chem": "chemistry",
    "chemistry": "chemistry",
    "cs": "computer science",
    "computer studies": "computer science",
    "computer study": "computer science",
    "computer science": "computer science",
    "biology": "biology",
    "bio": "biology",
    "it": "information technology",
    "information technology": "information technology",
}


def _norm(value: Any) -> str:
    text = str(value or "").casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _norm_subject(value: Any) -> str:
    norm = _norm(value)
    return _SUBJECT_ALIASES.get(norm, norm)


def _qualification_matches(value: Any, accepted: list[Any]) -> bool:
    """Conservative qualification normalization (specific routes remain specific)."""
    aliases = {
        "fsc pre engineering": "fsc pre engineering",
        "pre engineering": "fsc pre engineering",
        "pre eng": "fsc pre engineering",
        "fsc engineering": "fsc pre engineering",
        "ics": "ics",
        "intermediate in computer science": "ics",
        "fsc computer science": "ics",
        "fsc pre medical": "fsc pre medical",
        "pre medical": "fsc pre medical",
        "alevels": "a levels",
        "a level": "a levels",
        "gce a levels": "a levels",
        "hssc": "fsc",
        "higher secondary school certificate": "fsc",
    }

    def canonical(item: Any) -> str:
        cleaned = _norm(item)
        return aliases.get(cleaned, cleaned)

    student = canonical(value)
    accepted_canonical = {canonical(item) for item in accepted}
    if student in accepted_canonical:
        return True
    # A specifically stated FSc stream can satisfy a generic FSc requirement,
    # but a generic FSc cannot satisfy a specified stream requirement.
    return student in {"fsc pre engineering", "fsc pre medical"} and "fsc" in accepted_canonical


def _passes_subject_pathways(
    supplied: set[str],
    alternatives: list[list[str]],
) -> bool:
    """Each alternative is an AND group; any one complete group is sufficient."""
    pathways = [
        {_norm_subject(subject) for subject in path if _norm_subject(subject)}
        for path in alternatives
    ]
    pathways = [path for path in pathways if path]
    return any(path.issubset(supplied) for path in pathways)


def evaluate_eligibility(
    profile: Mapping[str, Any],
    rule: Mapping[str, Any] | None,
) -> EligibilityResult:
    """Evaluate explicitly configured rules; never infer missing official criteria.

    Rule fields include:
      verified, university_id, program_id, version, sources, cycle,
      accepted_qualifications, minimum_ssc_percent, minimum_hssc_percent,
      required_subjects, subject_alternatives, conditional_subject_alternatives,
      minimum_subject_percentages, require_ibcc_equivalence_for.
    Profile fields include:
      qualification, ssc_percent, hssc_percent, subjects, subject_percentages,
      equivalency_status, cycle.
    """
    empty = EligibilityResult(
        EligibilityStatus.INDETERMINATE,
        str((rule or {}).get("university_id", "unknown")),
        str((rule or {}).get("program_id", "unknown")),
        (rule or {}).get("version"),
        (RequirementResult("rule", "unknown", "No applicable source-verified rule was supplied."),),
        tuple(str(s) for s in ((rule or {}).get("sources") or ()) if s),
    )
    if not rule or rule.get("verified") is not True:
        return empty

    university_id = str(rule.get("university_id", "unknown"))
    program_id = str(rule.get("program_id", "unknown"))
    version = rule.get("version")
    sources = tuple(str(s) for s in (rule.get("sources") or ()) if s)
    checks: list[RequirementResult] = []
    missing = False
    failed = False
    conditional = False

    rule_cycle = rule.get("cycle")
    profile_cycle = profile.get("cycle")
    if rule_cycle and profile_cycle and str(rule_cycle) != str(profile_cycle):
        return EligibilityResult(
            EligibilityStatus.INDETERMINATE, university_id, program_id, version,
            (RequirementResult(
                "admission_cycle", "unknown",
                f"Rule applies to {rule_cycle}; profile specifies {profile_cycle}.",
            ),), sources,
        )
    if rule_cycle and not profile_cycle:
        missing = True
        checks.append(RequirementResult("admission_cycle", "unknown", "Admission cycle is required for a cycle-specific verdict."))

    qualification = profile.get("qualification")
    accepted = list(rule.get("accepted_qualifications") or [])
    if accepted:
        if not qualification:
            missing = True
            checks.append(RequirementResult("qualification", "unknown", "Academic qualification is missing."))
        elif not _qualification_matches(qualification, accepted):
            failed = True
            checks.append(RequirementResult("qualification", "fail",
                f"Qualification {qualification!r} does not match the qualifications listed in the source-backed rule."))
        else:
            checks.append(RequirementResult("qualification", "pass", "Qualification matches a listed accepted option."))

    for field, label, profile_field in (
        ("minimum_ssc_percent", "SSC percentage", "ssc_percent"),
        ("minimum_hssc_percent", "HSSC percentage", "hssc_percent"),
    ):
        threshold = rule.get(field)
        if threshold is None:
            continue
        value = profile.get(profile_field)
        if value is None:
            missing = True
            checks.append(RequirementResult(label, "unknown", f"{label} is required to evaluate the published minimum."))
            continue
        try:
            numeric, limit = float(value), float(threshold)
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

    # Subject alternatives are OR-of-AND groups. A conditional path may allow a
    # pre-medical student to proceed only with the explicitly published catch-up.
    supplied = profile.get("subjects")
    actual_subjects = {_norm_subject(s) for s in supplied} if supplied is not None else set()
    conditional_path_match = False
    matched_conditional_note = ""

    if not supplied and (rule.get("required_subjects") or rule.get("subject_alternatives") or rule.get("conditional_subject_alternatives")):
        missing = True
        checks.append(RequirementResult("subjects", "unknown", "HSSC subject list is needed to evaluate subject pathways."))
    else:
        conditional_paths = rule.get("conditional_subject_alternatives") or []
        for path in conditional_paths:
            allowed_quals = path.get("qualifications") or []
            qualification_ok = not allowed_quals or (
                qualification is not None and _qualification_matches(qualification, allowed_quals)
            )
            path_subjects = {_norm_subject(s) for s in (path.get("subjects") or [])}
            subject_ok = not path_subjects or path_subjects.issubset(actual_subjects)
            if qualification_ok and subject_ok:
                conditional_path_match = True
                matched_conditional_note = str(path.get("condition") or path.get("required_follow_up") or "An additional academic condition applies.")
                break

        required_subjects = {_norm_subject(s) for s in (rule.get("required_subjects") or [])}
        alternatives = rule.get("subject_alternatives") or []
        standard_path_match = not required_subjects.issubset(actual_subjects) if required_subjects else False
        if required_subjects:
            absent = sorted(required_subjects - actual_subjects)
            checks.append(RequirementResult(
                "required_subjects", "pass" if not absent else ("conditional" if conditional_path_match else "fail"),
                "All required subjects are present." if not absent else (
                    matched_conditional_note if conditional_path_match else "Missing required subjects: " + ", ".join(absent) + "."
                ),
            ))
            if absent and conditional_path_match:
                conditional = True
            elif absent:
                failed = True

        if alternatives:
            if supplied is None:
                pass
            elif _passes_subject_pathways(actual_subjects, alternatives):
                checks.append(RequirementResult("subject_pathway", "pass", "At least one listed subject pathway is satisfied."))
            elif conditional_path_match:
                conditional = True
                checks.append(RequirementResult("subject_pathway", "conditional", matched_conditional_note))
            else:
                failed = True
                formatted = " OR ".join(" + ".join(path) for path in alternatives)
                checks.append(RequirementResult(
                    "subject_pathway", "fail",
                    "The recorded subjects do not match any listed pathway (" + formatted + ").",
                ))

        if conditional_path_match:
            conditional = True
            # Avoid duplicate checks when an explicit required_subjects rule also
            # reported the same conditional route.
            if not any(c.requirement == "subject_pathway" and c.status == "conditional" for c in checks):
                checks.append(RequirementResult("conditional_pathway", "conditional", matched_conditional_note))

    # Published minima for named subjects, e.g. GIKI's Math/Physics minima.
    subject_thresholds = rule.get("minimum_subject_percentages") or {}
    percentages = profile.get("subject_percentages") or {}
    for subject, threshold in subject_thresholds.items():
        key = _norm_subject(subject)
        matching_value = next((v for k, v in percentages.items() if _norm_subject(k) == key), None)
        if matching_value is None:
            missing = True
            checks.append(RequirementResult(f"{key}_percentage", "unknown",
                f"A percentage for {key} is required by the published rule."))
            continue
        try:
            numeric, limit = float(matching_value), float(threshold)
        except (TypeError, ValueError):
            missing = True
            checks.append(RequirementResult(f"{key}_percentage", "unknown", f"{key} percentage must be numeric."))
            continue
        if not 0 <= numeric <= 100:
            missing = True
            checks.append(RequirementResult(f"{key}_percentage", "unknown", f"{key} percentage must be between 0 and 100."))
        elif numeric < limit:
            failed = True
            checks.append(RequirementResult(f"{key}_percentage", "fail",
                f"{numeric:g}% in {key} is below the published minimum of {limit:g}%."))
        else:
            checks.append(RequirementResult(f"{key}_percentage", "pass",
                f"{numeric:g}% in {key} meets the published minimum of {limit:g}%."))

    ibcc_required_for = {_norm(q) for q in (rule.get("require_ibcc_equivalence_for") or [])}
    if qualification and _norm(qualification) in ibcc_required_for:
        equivalency_status = _norm(profile.get("equivalency_status"))
        if not equivalency_status:
            missing = True
            checks.append(RequirementResult("ibcc_equivalence", "unknown",
                "IBCC equivalence status is required for this foreign qualification."))
        elif equivalency_status in {"verified", "approved", "issued", "complete", "completed", "yes", "true", "obtained"}:
            checks.append(RequirementResult("ibcc_equivalence", "pass", "IBCC equivalence is recorded as issued/verified."))
        else:
            failed = True
            checks.append(RequirementResult("ibcc_equivalence", "fail",
                "A valid IBCC equivalence certificate is required for this qualification."))

    if not checks:
        checks.append(RequirementResult("rule", "unknown", "No supported deterministic checks are configured."))
        missing = True

    status = (
        EligibilityStatus.INELIGIBLE if failed else
        EligibilityStatus.INDETERMINATE if missing else
        EligibilityStatus.CONDITIONALLY_ELIGIBLE if conditional else
        EligibilityStatus.ELIGIBLE
    )
    return EligibilityResult(status, university_id, program_id, version, tuple(checks), sources)
