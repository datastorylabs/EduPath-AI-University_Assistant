"""Public, source-provenanced admissions catalogue and eligibility API."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.app.services.admissions_catalog import (
    get_available_rule,
    get_rule_record,
    get_source_registry_metadata,
    list_available_rules,
    list_universities,
    load_sources_registry,
)
from backend.app.services.admissions_rules import EligibilityStatus, evaluate_eligibility


router = APIRouter(prefix="/admissions", tags=["admissions"])


class AcademicProfileInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    qualification: str | None = Field(default=None, max_length=120)
    ssc_percent: float | None = Field(default=None, ge=0, le=100)
    hssc_percent: float | None = Field(default=None, ge=0, le=100)
    subjects: list[str] | None = Field(default=None, max_length=32)
    subject_percentages: dict[str, float] = Field(default_factory=dict)
    equivalency_status: str | None = Field(default=None, max_length=40)
    cycle: str | None = Field(default=None, max_length=40)


class EvaluateAdmissionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    university_id: str = Field(min_length=1, max_length=80)
    program_id: str = Field(min_length=1, max_length=120)
    cycle: str = Field(min_length=4, max_length=40)
    profile: AcademicProfileInput


class CompareAdmissionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_family: str = Field(min_length=1, max_length=80)
    cycle: str = Field(min_length=4, max_length=40)
    university_ids: list[str] = Field(default_factory=list, max_length=20)


@router.get("/catalog", summary="Admissions research coverage overview")
def admissions_catalog_overview() -> dict[str, Any]:
    registry = get_source_registry_metadata()
    rules = list_available_rules()
    evaluable = [rule for rule in rules if rule["evaluation_available"]]
    return {
        **registry,
        "evaluable_rule_count": len(evaluable),
        "evaluated_rule_keys": [
            {
                "university_id": rule["university_id"],
                "program_id": rule["program_id"],
                "program_name": rule.get("program_name"),
                "cycle": rule["cycle"],
                "version": rule.get("version"),
            }
            for rule in evaluable
        ],
        "coverage_notice": (
            "This is a growing catalog, not complete national coverage. An institution without a "
            "source-verified rule is not assumed eligible or ineligible."
        ),
    }


@router.get("/universities", summary="Universities with official-source coverage metadata")
def admissions_universities() -> dict[str, Any]:
    return {
        "universities": list_universities(),
        "coverage_notice": (
            "University listing means a source lead exists; it does not mean the university's "
            "program criteria, campuses, or active intake have all been researched."
        ),
    }


@router.get("/sources", summary="Official admissions source records")
def admissions_sources(
    university_id: str | None = Query(default=None, min_length=1, max_length=80),
    verification_status: str | None = Query(default=None, min_length=1, max_length=40),
) -> dict[str, Any]:
    registry = load_sources_registry()
    sources = registry["sources"]
    if university_id:
        sources = [item for item in sources if item["university_id"] == university_id]
    if verification_status:
        allowed = {"verified", "partially_verified", "unverified", "stale", "conflicting"}
        if verification_status not in allowed:
            raise HTTPException(status_code=422, detail="Unsupported verification status.")
        sources = [item for item in sources if item["verification_status"] == verification_status]
    return {
        "sources": sources,
        "count": len(sources),
        "verification_policy": registry.get("verification_policy", {}),
    }


@router.get("/rules", summary="Program rules with explicit source-verification state")
def admissions_rules(
    university_id: str | None = Query(default=None, min_length=1, max_length=80),
    cycle: str | None = Query(default=None, min_length=4, max_length=40),
    evaluable_only: bool = False,
) -> dict[str, Any]:
    rules = list_available_rules(university_id=university_id, cycle=cycle)
    if evaluable_only:
        rules = [rule for rule in rules if rule["evaluation_available"]]
    return {
        "rules": rules,
        "count": len(rules),
        "evaluable_count": sum(1 for rule in rules if rule["evaluation_available"]),
    }


@router.post("/evaluate", summary="Evaluate a student's profile against a source-verified rule")
def evaluate_admissions(payload: EvaluateAdmissionsRequest) -> dict[str, Any]:
    """Evaluate without storing the submitted academic profile."""
    if payload.profile.cycle and payload.profile.cycle != payload.cycle:
        # Preserve the conflicting value so the evaluator returns indeterminate.
        profile = payload.profile.model_dump()
    else:
        profile = payload.profile.model_dump()
        profile["cycle"] = payload.cycle

    rule = get_available_rule(payload.university_id, payload.program_id, payload.cycle)
    record = get_rule_record(payload.university_id, payload.program_id, payload.cycle)

    if rule is None:
        # Do not silently substitute another cycle or an approximate rule.
        if record is not None:
            available = next(
                (
                    item for item in list_available_rules(
                        university_id=payload.university_id, cycle=payload.cycle
                    )
                    if item["program_id"] == payload.program_id
                ),
                None,
            )
            source_urls = available.get("sources", []) if available else []
            block_reason = (
                available.get("evaluation_block_reason")
                if available else "Rule exists but cannot be verified against a current official source."
            )
        else:
            source_urls = [
                item["url"]
                for item in load_sources_registry()["sources"]
                if item["university_id"] == payload.university_id and item.get("url")
            ]
            block_reason = "No program-specific verified rule exists for this university and cycle."

        unavailable_result = evaluate_eligibility(
            profile,
            {
                "verified": False,
                "university_id": payload.university_id,
                "program_id": payload.program_id,
                "cycle": payload.cycle,
                "version": record.get("version") if record else None,
                "sources": source_urls,
            },
        ).to_dict()
        unavailable_result["rule_availability"] = {
            "available": False,
            "cycle": payload.cycle,
            "reason": block_reason,
        }
        unavailable_result["source_urls"] = source_urls
        return unavailable_result

    result = evaluate_eligibility(profile, rule).to_dict()
    result["rule_availability"] = {
        "available": True,
        "cycle": rule["cycle"],
        "version": rule["version"],
    }
    result["source_details"] = rule.get("source_details", [])
    return result


@router.post("/compare", summary="Compare currently evaluable rules within one program family")
def compare_admissions(payload: CompareAdmissionsRequest) -> dict[str, Any]:
    rules = [
        rule for rule in list_available_rules(cycle=payload.cycle)
        if rule.get("program_family") == payload.program_family and rule["evaluation_available"]
    ]
    if payload.university_ids:
        requested = set(payload.university_ids)
        rules = [rule for rule in rules if rule["university_id"] in requested]

    available_universities = {rule["university_id"] for rule in rules}
    missing = [
        university_id for university_id in payload.university_ids
        if university_id not in available_universities
    ]
    return {
        "program_family": payload.program_family,
        "cycle": payload.cycle,
        "rules": rules,
        "university_ids_without_verified_rule": missing,
        "notice": (
            "Only source-verified rule records for the requested cycle are compared. "
            "Universities missing from this response are unknown, not automatically unsuitable."
        ),
    }
