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

    from backend.rag.retriever import detect_intent

    intent = detect_intent(question)
    named_ids = list(intent.get("university_ids") or [])
    compare_named = len(named_ids) >= 2
    selected_uid = selected_uni.get("id") if selected_uni else selected_university_id
    excluded_ids = set()
    if not compare_named:
        if selected_uid:
            excluded_ids.add(selected_uid)
        if named_ids and re.search(r"\b(?:other\s+than|apart\s+from|besides|instead\s+of)\b", question.casefold()):
            excluded_ids.update(named_ids)

    candidates: list[dict[str, Any]] = []
    for university in universities:
        uid = university.get("id")
        if not uid or uid in excluded_ids:
            continue
        if compare_named and uid not in named_ids:
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
    if compare_named:
        named_names = [
            uni.get("name", uni.get("id", "University"))
            for uni in universities if uni.get("id") in named_ids
        ]
        lines = [
            f"Here's a comparison of **{', '.join(named_names)}** for programs related to **{target_prog_name}**, using the academic baselines recorded in EduPath's catalog."
        ]
    else:
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
    if not compare_named:
        target_name = str(selected_program.get("name", "")).casefold()
        target_category = str(selected_program.get("category", "")).casefold()
        if any(term in target_name for term in COMPUTING_TERMS) or target_category in {"computing", "computer science"}:
            extra_ids = {"giki", "iba-karachi"}
        elif "engineering" in target_name or target_category == "engineering":
            extra_ids = {"giki", "ned"}
        elif any(term in target_name for term in ("business", "accounting", "finance")) or target_category == "business":
            extra_ids = {"iba-karachi"}
        else:
            extra_ids = set()

        catalog_ids = {str(uni.get("id")) for uni in universities}
        if extra_ids - catalog_ids:
            try:
                from backend.app.services.admissions_catalog import load_sources_registry
                extra_sources = load_sources_registry()["sources"]
            except Exception:
                extra_sources = []
            extra_lines: list[str] = []
            for extra_id in sorted(extra_ids - catalog_ids):
                records = [source for source in extra_sources if source.get("university_id") == extra_id]
                if not records:
                    continue
                source = next(
                    (record for record in records if record.get("verification_status") == "partially_verified"),
                    records[0],
                )
                extra_display_names = {
                    "giki": "GIKI",
                    "iba-karachi": "IBA Karachi",
                    "ned": "NED University",
                }
                extra_lines.append(
                    f"- **{extra_display_names.get(extra_id, extra_id)}**: {source.get('scope', 'Official source located; program-level details are incomplete.')} "
                    f"Status: {source.get('verification_status', 'unverified')}. "
                    f"Official source: {source.get('url', '(not recorded)')}. "
                    "Not profile-scored because a cycle-specific program rule is not in the structured catalog."
                )
            if extra_lines:
                lines.append("**Additional official leads (not yet scored against your profile)**")
                lines.extend(extra_lines)

    lines.append(
        "These are shortlist leads, not admission guarantees. Campus availability and intake rules can differ. "
        "I have not changed your selected program. Tell me your preferred city or budget if you want the shortlist narrowed."
    )
    return "\n".join(lines)



def answer_named_university(
    question: str,
    profile: dict[str, Any] | None,
    selected_university_id: str | None,
    selected_program_id: str | None,
    target_university_id: str,
) -> str:
    """Answer a named-university follow-up without reusing another school's verdict."""
    from backend.data_loader import get_program, get_university, load_universities

    profile = profile or {}
    data = load_universities()
    universities = data.get("universities", []) or []
    target_university = get_university(data, target_university_id)

    selected_university = (
        get_university(data, selected_university_id) if selected_university_id else None
    )
    selected_program = (
        get_program(selected_university, selected_program_id)
        if selected_university and selected_program_id else None
    )
    target_program_name = str(
        profile.get("target_program") or (selected_program or {}).get("name") or ""
    )

    # The primary catalogue contains program details for only a subset of
    # institutions. For universities outside it, use the separate source registry
    # to give the user an official starting point without manufacturing criteria.
    if target_university is None:
        registry_id_aliases = {
            "uet": "uet-lahore",
            "uok": "university-of-karachi",
            "pu": "punjab-university",
            "iba": "iba-karachi",
        }
        registry_id = registry_id_aliases.get(target_university_id, target_university_id)
        try:
            from backend.app.services.admissions_catalog import load_sources_registry
            source_records = [
                item for item in load_sources_registry()["sources"]
                if item["university_id"] == registry_id
            ]
        except Exception:
            source_records = []

        if not source_records:
            return (
                f"I recognized the university you asked about, but it has no source record available "
                f"in this EduPath build yet. Your previously selected university's eligibility result "
                f"does not apply to {target_university_id}. I won't invent its criteria."
            )

        # Prefer a current/official policy page over an institutional homepage.
        source_records.sort(key=lambda item: (
            item.get("verification_status") == "unverified",
            item.get("source_type") in {"official_admissions_page", "official_admissions_portal"},
        ))
        lines = [
            f"You're asking about **{source_records[0].get('title', target_university_id)}**, rather than just the next step for your current choice."
        ]
        status = source_records[0].get("verification_status", "unverified")
        lines.append(
            f"EduPath has an official source lead for this university, but the source record is **{status.replace('_', ' ')}**. "
            "It does not currently provide a source-verified, program-specific rule in the local eligibility engine."
        )
        for source in source_records[:3]:
            lines.append(f"- [{source.get('title', 'Official source')}]({source['url']}) — {source.get('scope', 'scope not recorded')}")
        lines.append(
            "That means I can point you to the official criteria, but I cannot safely reuse your current university's verdict or declare you eligible here. "
            "Tell me the exact degree and intake if you want a program-specific comparison."
        )
        return "\n".join(lines)

    programs = target_university.get("programs", []) or []
    query = (question or "").casefold()
    exact = [
        program for program in programs
        if len(str(program.get("name", ""))) > 4
        and str(program.get("name", "")).casefold() in query
    ]

    if exact:
        candidates = exact
    else:
        target_category = str((selected_program or {}).get("category", "")).casefold()
        target_name = target_program_name.casefold()
        keywords = {
            "computing": {"artificial intelligence", "computer science", "data science", "software engineering", "cyber security", "computer engineering", "information technology"},
            "engineering": {"engineering", "electrical", "mechanical", "civil", "chemical", "mechatronics", "telecommunication"},
            "business": {"business administration", "business analytics", "accounting", "finance", "economics"},
        }
        if target_category in {"computing", "computer science", "information technology"} or any(
            word in target_name for word in ("artificial intelligence", "computer science", "data science", "software", "cyber")
        ):
            family = keywords["computing"]
        elif target_category == "engineering" or "engineering" in target_name:
            family = keywords["engineering"]
        elif target_category == "business" or "business" in target_name:
            family = keywords["business"]
        else:
            family = set(re.findall(r"[a-z]+", target_name))

        candidates = [
            program for program in programs
            if str(program.get("category", "")).casefold() == target_category
            or any(term in str(program.get("name", "")).casefold() for term in family)
        ]
        candidates.sort(
            key=lambda program: (-_term_score(selected_program or {"name": target_program_name}, program),
                                 str(program.get("name", "")))
        )

    candidates = candidates[:4]
    if not candidates:
        return (
            f"**{target_university.get('name', target_university_id)}** is in EduPath's program catalog, "
            "but I couldn't identify a related program from the catalog. This does not mean the university "
            "has no suitable option; the catalog's program list may be incomplete."
        )

    source_urls = [
        source.get("url") for source in target_university.get("sources", []) or []
        if source.get("url")
    ]
    source_line = source_urls[0] if source_urls else target_university.get("website")
    lines = [
        f"Here are related options at **{target_university['name']}** based on EduPath's local catalog. "
        "This is a separate university lookup—not an extension of your selected program's eligibility verdict."
    ]
    for program in candidates:
        req = program.get("requirements", {}) or {}
        lines.append(f"**{program.get('name', 'Program')}**")
        if req.get("qualification"):
            lines.append("- Listed qualifications: " + ", ".join(str(item) for item in req["qualification"]) + ".")
        if req.get("minimum_aggregate") is not None:
            lines.append(f"- Catalog-listed minimum: {req['minimum_aggregate']}%. Confirm whether this means HSSC marks or a programme-specific aggregate.")
        if req.get("admission_test"):
            lines.append(f"- Admission test listed: {req['admission_test']}.")
        if req.get("application_deadline"):
            lines.append(f"- Catalog deadline: {req['application_deadline']}; confirm it against the active intake.")
        if req.get("estimated_cutoff") is None:
            lines.append("- Closing merit is not recorded; I won't estimate your admission chance.")
    if source_line:
        lines.append(f"**Official university source:** {source_line}")
    lines.append(
        f"The catalog says its university-level information was last checked on {target_university.get('last_verified', 'an unrecorded date')}. "
        "Verify program-specific requirements, campus availability, and the active admission cycle on the official source before acting."
    )
    return "\n".join(lines)
