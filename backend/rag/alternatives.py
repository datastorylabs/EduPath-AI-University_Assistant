"""Catalog-based university alternatives for when the LLM is unavailable.

These suggestions are shortlist leads, not admission guarantees. They use only
programs already present in the catalog and never fabricate missing criteria.
"""
from __future__ import annotations

import re
from typing import Any


COMPUTING_TERMS = {
    "artificial intelligence", "computer science", "data science",
    "software engineering", "cyber security", "cybersecurity",
    "computer engineering", "robotics", "information technology",
    "computing", "business analytics",
}
ENGINEERING_TERMS = {
    "engineering", "electrical", "mechanical", "civil", "chemical",
    "mechatronics", "telecommunication", "petroleum", "materials",
}


def _term_score(target: dict[str, Any], candidate: dict[str, Any]) -> int:
    target_name = str(target.get("name", "")).casefold()
    candidate_name = str(candidate.get("name", "")).casefold()
    target_category = str(target.get("category", "")).casefold()
    candidate_category = str(candidate.get("category", "")).casefold()

    if target_category and target_category == candidate_category:
        score = 4
    else:
        score = 0

    family = COMPUTING_TERMS if any(term in target_name for term in COMPUTING_TERMS) else (
        ENGINEERING_TERMS if "engineering" in target_name or target_category == "engineering" else set()
    )
    if family and any(term in candidate_name for term in family):
        score += 5
    if target_name and (target_name in candidate_name or candidate_name in target_name):
        score += 3
    target_tokens = {
        token for token in re.findall(r"[a-z]+", target_name)
        if len(token) >= 4 and token not in {"bachelor", "science", "degree", "honours", "honors"}
    }
    candidate_tokens = set(re.findall(r"[a-z]+", candidate_name))
    score += len(target_tokens & candidate_tokens)
    return score


def answer_alternative_universities(
    question: str,
    profile: dict[str, Any] | None,
    selected_university_id: str | None,
    selected_program_id: str | None,
    *,
    universities_data: dict[str, Any] | None = None,
    limit: int = 5,
) -> str:
    """Give a concrete cross-university shortlist from the local program catalog."""
    from backend.data_loader import load_universities, get_university, get_program

    profile = profile or {}
    data = universities_data if universities_data is not None else load_universities()
    universities = data.get("universities", []) or []
    selected_uni = get_university(data, selected_university_id) if selected_university_id else None
    selected_program = get_program(selected_uni, selected_program_id) if selected_uni and selected_program_id else None

    if selected_program is None:
        selected_name = profile.get("target_program")
        for uni in universities:
            for program in uni.get("programs", []) or []:
                if selected_name and program.get("name") == selected_name:
                    selected_uni, selected_program = uni, program
                    break
            if selected_program:
                break

    if not selected_program:
        return (
            "You're asking for university alternatives, not another action checklist. "
            "I can compare the programs in EduPath's catalog, but I need a target subject or program "
            "to choose meaningful alternatives. The catalog currently covers only a subset of Pakistani universities."
        )

    try:
        from backend.eligibility import _qualification_matches
    except Exception:
        _qualification_matches = None

    qualification = profile.get("qualification")
    aggregate = profile.get("aggregate")
    if aggregate is None:
        aggregate = profile.get("hssc_percentage")
    try:
        aggregate_value = float(aggregate) if aggregate is not None else None
    except (TypeError, ValueError):
        aggregate_value = None

    selected_uid = selected_uni.get("id") if selected_uni else selected_university_id
    candidates: list[dict[str, Any]] = []
    for university in universities:
        uid = university.get("id")
        if not uid or uid == selected_uid:
            continue
        for program in university.get("programs", []) or []:
            relevance = _term_score(selected_program, program)
            if relevance < 3:
                continue
            req = program.get("requirements", {}) or {}
            accepted = req.get("qualification", []) or []
            if qualification and accepted and _qualification_matches:
                qualification_match: bool | None = _qualification_matches(str(qualification), accepted)
            else:
                qualification_match = None

            minimum = req.get("minimum_aggregate")
            try:
                minimum_value = float(minimum) if minimum is not None else None
            except (TypeError, ValueError):
                minimum_value = None
            marks_meet_minimum = (
                aggregate_value >= minimum_value
                if aggregate_value is not None and minimum_value is not None
                else None
            )
            source_url = None
            for source in university.get("sources", []) or []:
                url = source.get("url")
                if url and any(word in url.casefold() for word in ("admission", "eligibility", "programoffered", "program")):
                    source_url = url
                    break
            if not source_url:
                source_url = university.get("website")

            # Rank confirmed profile matches first, then entries requiring
            # less guessing; a null threshold is never treated as a pass.
            match_rank = 2 if qualification_match is True and marks_meet_minimum is True else (
                1 if qualification_match is not False and marks_meet_minimum is not False else 0
            )
            candidates.append({
                "university": university,
                "program": program,
                "relevance": relevance,
                "qualification_match": qualification_match,
                "minimum": minimum_value,
                "marks_meet_minimum": marks_meet_minimum,
                "source_url": source_url,
                "match_rank": match_rank,
            })

    # Use only reasonable subject matches. When too few data-backed matches
    # exist, include unknowns before displaying known mismatches.
    candidates.sort(
        key=lambda item: (
            -item["match_rank"],
            -item["relevance"],
            item["university"].get("name", ""),
            item["program"].get("name", ""),
        )
    )
    useful = [item for item in candidates if item["match_rank"] > 0][:max(1, limit)]

    target_uni_name = selected_uni.get("name") if selected_uni else profile.get("target_university", "your selected university")
    target_prog_name = selected_program.get("name", "your selected program")
    lines = [
        f"You're right to explore alternatives. You're currently looking at **{target_prog_name}** at **{target_uni_name}**; here are other universities in EduPath's catalog with related programs."
    ]
    if not useful:
        lines.append(
            "I couldn't identify a reliable alternative match from the stored criteria and your current profile. "
            "That is a data limitation, not proof that other universities are unsuitable."
        )
        lines.append(
            "The catalog has incomplete campus- and cycle-level criteria, so I won't label a school eligible without enough information."
        )
        return "\n\n".join(lines)

    for item in useful:
        university = item["university"]
        program = item["program"]
        req = program.get("requirements", {}) or {}
        qualification_match = item["qualification_match"]
        marks_meet = item["marks_meet_minimum"]
        minimum = item["minimum"]

        if qualification_match is True and marks_meet is True:
            fit = "Potential fit: your recorded qualification and marks meet the catalog's listed baseline."
        elif qualification_match is True and marks_meet is None:
            fit = "Possible option: qualification appears to match, but a comparable minimum-mark rule is not recorded."
        elif qualification_match is None or marks_meet is None:
            fit = "Needs checking: the catalog does not contain enough comparable information to confirm a baseline match."
        else:
            fit = "Not a strong match on the profile currently recorded; check the alternative route only if the official criteria support it."

        lines.append(f"**{university.get('name', 'University')} — {program.get('name', 'Program')}**")
        lines.append(f"- {fit}")
        if minimum is not None:
            lines.append(f"- Catalog-listed minimum: {minimum:g}% (confirm which marks/aggregate definition the program uses).")
        if req.get("admission_test"):
            lines.append(f"- Admission test listed: {req['admission_test']}.")
        if req.get("estimated_cutoff") is None:
            lines.append("- A reliable closing-merit cutoff is not recorded; I won't estimate your admission chances.")
        if item["source_url"]:
            lines.append(f"- Official starting point: {item['source_url']}")
    lines.append(
        "These are shortlist leads, not admission guarantees. Campus availability and intake rules can differ. "
        "I have not changed your selected program. Tell me your preferred city or budget if you want the shortlist narrowed."
    )
    return "\n".join(lines)
