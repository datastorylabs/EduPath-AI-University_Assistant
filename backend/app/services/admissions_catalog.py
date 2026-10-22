"""Source-checked access to the structured admissions registry and rule records."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from backend.app.services.admissions_sources import is_stale, validate_source_record


APP_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = APP_ROOT / "data"
SOURCE_REGISTRY_PATH = DATA_DIR / "admissions_sources.json"
RULES_PATH = DATA_DIR / "admissions_rules.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Admissions data could not be loaded from {path.name}.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Admissions data file {path.name} must contain a JSON object.")
    return payload


def load_sources_registry() -> dict[str, Any]:
    payload = _read_json(SOURCE_REGISTRY_PATH)
    records = payload.get("sources")
    if not isinstance(records, list):
        raise RuntimeError("Admissions source registry must contain a sources array.")
    errors: list[str] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"sources[{index}]_must_be_object")
            continue
        errors.extend(f"sources[{index}]:{error}" for error in validate_source_record(record))
        source_id = record.get("source_id")
        if source_id in seen:
            errors.append(f"sources[{index}]:duplicate_source_id")
        if source_id:
            seen.add(source_id)
    if errors:
        raise RuntimeError("Invalid admissions source registry: " + "; ".join(errors[:12]))
    return payload


def load_rule_records() -> list[dict[str, Any]]:
    payload = _read_json(RULES_PATH)
    records = payload.get("rules")
    if not isinstance(records, list):
        raise RuntimeError("Admissions rules data must contain a rules array.")
    seen: set[tuple[str, str, str]] = set()
    for index, rule in enumerate(records):
        if not isinstance(rule, dict):
            raise RuntimeError(f"Rule record {index} must be an object.")
        key = (
            str(rule.get("university_id", "")),
            str(rule.get("program_id", "")),
            str(rule.get("cycle", "")),
        )
        if not all(key):
            raise RuntimeError(f"Rule record {index} is missing university_id, program_id, or cycle.")
        if key in seen:
            raise RuntimeError(f"Duplicate rule record for {key}.")
        seen.add(key)
        if rule.get("verification_status") not in {"verified", "partially_verified", "unverified", "stale", "conflicting"}:
            raise RuntimeError(f"Rule record {index} has an invalid verification_status.")
    return records


def _source_index(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(record["source_id"]): record for record in registry["sources"]}


def _rule_source_state(
    rule: dict[str, Any],
    source_index: dict[str, dict[str, Any]],
    *,
    today: date,
    max_age_days: int = 180,
) -> tuple[bool, list[dict[str, str]], str | None]:
    source_ids = rule.get("source_ids") or []
    if not source_ids:
        return False, [], "No source IDs are attached to this rule."

    sources: list[dict[str, str]] = []
    for source_id in source_ids:
        source = source_index.get(str(source_id))
        if source is None:
            return False, sources, f"Source record {source_id!r} is missing."
        sources.append({
            "source_id": str(source["source_id"]),
            "title": str(source.get("title", "")),
            "url": str(source.get("url", "")),
            "admission_cycle": str(source.get("admission_cycle", "")),
            "verification_status": str(source.get("verification_status", "")),
        })
        if source.get("verification_status") == "conflicting":
            return False, sources, "Official sources conflict; this rule cannot be evaluated safely."
        if source.get("verification_status") != "verified":
            return False, sources, f"Source {source_id!r} is not fully verified."
        if validate_source_record(source):
            return False, sources, f"Source {source_id!r} has invalid metadata."
        if is_stale(source, today=today, max_age_days=max_age_days):
            return False, sources, f"Source {source_id!r} needs a fresh review."
        if str(source.get("admission_cycle", "")) != str(rule.get("cycle", "")):
            return False, sources, f"Source {source_id!r} covers a different admission cycle."
    return True, sources, None


def _public_rule(
    rule: dict[str, Any],
    source_index: dict[str, dict[str, Any]],
    *,
    today: date,
) -> dict[str, Any]:
    source_ok, source_info, reason = _rule_source_state(rule, source_index, today=today)
    valid_until = rule.get("valid_until")
    if valid_until:
        try:
            if today > date.fromisoformat(str(valid_until)):
                source_ok = False
                reason = "The rule's configured validity date has passed."
        except ValueError:
            source_ok = False
            reason = "The rule contains an invalid validity date."

    rule_ok = (
        rule.get("verification_status") == "verified"
        and source_ok
    )
    return {
        **rule,
        "verified": rule_ok,
        "sources": [s["url"] for s in source_info if s.get("url")],
        "source_details": source_info,
        "evaluation_available": rule_ok,
        "evaluation_block_reason": None if rule_ok else (
            reason or "The rule is not marked verified."
        ),
    }


def list_available_rules(
    *,
    university_id: str | None = None,
    cycle: str | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Return rule records with their source-derived evaluation availability."""
    effective_today = today or date.today()
    registry = load_sources_registry()
    source_index = _source_index(registry)
    results = []
    for rule in load_rule_records():
        if university_id and rule.get("university_id") != university_id:
            continue
        if cycle and str(rule.get("cycle")) != str(cycle):
            continue
        results.append(_public_rule(rule, source_index, today=effective_today))
    return results


def get_available_rule(
    university_id: str,
    program_id: str,
    cycle: str,
    *,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Get a matching rule only when its source evidence still supports evaluation."""
    for rule in list_available_rules(university_id=university_id, cycle=cycle, today=today):
        if rule.get("program_id") == program_id and rule.get("evaluation_available"):
            return rule
    return None


def get_rule_record(
    university_id: str,
    program_id: str,
    cycle: str,
) -> dict[str, Any] | None:
    for rule in load_rule_records():
        if (
            rule.get("university_id") == university_id
            and rule.get("program_id") == program_id
            and str(rule.get("cycle")) == str(cycle)
        ):
            return rule
    return None


def list_universities(*, today: date | None = None) -> list[dict[str, Any]]:
    """Group universities and expose source coverage without implying full research."""
    registry = load_sources_registry()
    source_index = _source_index(registry)
    university_names = {
        "fast-nuces": "FAST-NUCES",
        "nust": "NUST",
        "comsats": "COMSATS University Islamabad",
        "giki": "GIKI",
        "lums": "LUMS",
        "uet-lahore": "UET Lahore",
        "muet": "Mehran University of Engineering and Technology (MUET)",
        "ned": "NED University of Engineering and Technology",
        "university-of-karachi": "University of Karachi",
        "punjab-university": "University of the Punjab",
        "iba-karachi": "Institute of Business Administration Karachi (IBA)",
    }
    records: dict[str, dict[str, Any]] = {}
    for source in registry["sources"]:
        uid = str(source["university_id"])
        item = records.setdefault(uid, {
            "university_id": uid,
            "university_name": university_names.get(uid, uid),
            "sources": [],
            "verified_rule_count": 0,
        })
        item["sources"].append({
            "source_id": source["source_id"],
            "title": source["title"],
            "url": source["url"],
            "admission_cycle": source["admission_cycle"],
            "verification_status": source["verification_status"],
            "scope": source.get("scope", ""),
            "last_verified": source.get("last_verified"),
        })

    for rule in list_available_rules(today=today):
        item = records.setdefault(
            str(rule["university_id"]),
            {
                "university_id": rule["university_id"],
                "university_name": university_names.get(str(rule["university_id"]), str(rule["university_id"])),
                "sources": [],
                "verified_rule_count": 0,
            },
        )
        if rule["evaluation_available"]:
            item["verified_rule_count"] += 1

    # Preserve source-discovery entries with zero rules, and report status summary.
    for item in records.values():
        statuses = [s["verification_status"] for s in item["sources"]]
        item["source_status_summary"] = {
            status: statuses.count(status)
            for status in ("verified", "partially_verified", "unverified", "stale", "conflicting")
            if status in statuses
        }
        # The current dataset is intentionally a partial coverage registry;
        # one or two verified rules must never be presented as university-wide
        # admissions research completeness.
        item["has_evaluable_rules"] = item["verified_rule_count"] > 0
        item["research_complete"] = False
    return sorted(records.values(), key=lambda item: item["university_id"])


def get_source_registry_metadata() -> dict[str, Any]:
    registry = load_sources_registry()
    return {
        "schema_version": registry.get("schema_version"),
        "generated_on": registry.get("generated_on"),
        "purpose": registry.get("purpose"),
        "verification_policy": registry.get("verification_policy", {}),
        "source_count": len(registry.get("sources", [])),
        "university_count": len({s.get("university_id") for s in registry.get("sources", [])}),
    }
