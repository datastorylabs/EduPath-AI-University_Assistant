"""Synthesize per-program policy text files from data/universities.json.

The JSON is the single source of truth. These files are committed to the
repository as the RAG retrieval corpus. The synthesizer is deterministic:
the same JSON always produces the same files and contents.
"""
from __future__ import annotations

import json
from datetime import date, timezone
from pathlib import Path
from typing import Any

from backend.rag.config import POLICIES_DIR, UNIVERSITIES_PATH


def _section(title: str, body: str) -> str:
    if not body or not body.strip():
        return ""
    return f"## {title}\n\n{body.strip()}\n\n"


def _doc_line(doc: dict[str, Any]) -> str:
    required = "required" if doc.get("required", True) else "optional"
    return f"- {doc['name']} ({required})"


def _build_program_text(program: dict[str, Any], university: dict[str, Any]) -> str:
    reqs = program.get("requirements", {})
    qualifications = reqs.get("qualification", []) or []
    quals = "\n".join(f"- {q}" for q in qualifications) if qualifications else "- (not specified)"
    docs = "\n".join(_doc_line(d) for d in reqs.get("required_documents", []) or []) or "- (not specified)"

    out = f"# {university['name']} — {program['name']}\n\n"
    out += f"University full name: {university.get('full_name', university['name'])}.\n"
    out += f"Location: {university.get('location', '(unknown)')}. "
    out += f"Program duration: {program.get('duration', '(unknown)')}.\n\n"

    out += _section("Eligibility", quals)
    min_agg = reqs.get("minimum_aggregate")
    cutoff = reqs.get("estimated_cutoff")
    formula = reqs.get("aggregate_formula")
    test = reqs.get("admission_test")
    out += _section(
        "Aggregate",
        f"Minimum aggregate: {min_agg if min_agg is not None else '(unknown)'}%.\n"
        f"Estimated merit cutoff: {cutoff if cutoff is not None else '(unknown)'}%.\n"
        f"Aggregate formula: {formula or '(not specified)'}.",
    )
    out += _section(
        "Admission Test",
        f"{test or '(not specified)'}.",
    )
    out += _section("Required Documents", docs)

    deadline = reqs.get("application_deadline")
    out += _section(
        "Deadline",
        f"Application deadline: {deadline or '(not specified)'}."
        + (
            " The verified year for this deadline is "
            f"{str(deadline)[:4]}."
            if deadline
            else ""
        ),
    )

    fee = reqs.get("fee_estimate_pkr")
    out += _section(
        "Fees",
        f"Estimated fee: PKR {fee:,}."
        if isinstance(fee, int)
        else "Estimated fee: (not specified).",
    )
    out += _section("Notes", reqs.get("notes", "") or "")
    source_lines = [
        f"- {source.get('title', 'Official university source')}: {source.get('url', '(URL not recorded)')} "
        f"(last checked {source.get('last_verified', '(date not recorded)')}; "
        f"status {source.get('verification_status', 'not recorded')})"
        for source in (university.get("sources", []) or [])
    ]
    source_notice = (
        "Source records are attached at university level unless their scope says otherwise. "
        "They do not independently prove every generated program detail, campus offering, intake, "
        "deadline, or criterion. Treat missing/uncertain values as unknown and confirm them on the "
        "official source for the relevant program and cycle."
    )
    out += _section("Sources and verification limits", "\n".join(source_lines + [source_notice]))
    return out.strip() + "\n"


def _build_registry_source_text(record: dict[str, Any]) -> str:
    """Create a retrieval document for one official source with explicit limits."""
    university_names = {
        "fast-nuces": "FAST-NUCES",
        "nust": "NUST",
        "comsats": "COMSATS University Islamabad",
        "giki": "GIKI",
        "lums": "LUMS",
        "uet-lahore": "UET Lahore",
        "muet": "MUET",
        "ned": "NED University",
        "university-of-karachi": "University of Karachi",
        "punjab-university": "University of the Punjab",
        "iba-karachi": "IBA Karachi",
    }
    uid = str(record.get("university_id", "unknown"))
    title = str(record.get("title", "Official admissions source"))
    out = f"# {university_names.get(uid, uid)} — Official source: {title}\n\n"
    out += f"Source ID: {record.get('source_id', '(not recorded)')}\n"
    out += f"Official source URL: {record.get('url', '(not recorded)')}\n"
    out += f"Verification status: {record.get('verification_status', 'unverified')}\n"
    out += f"Admission cycle: {record.get('admission_cycle', 'not specified')}\n"
    out += f"Last verified: {record.get('last_verified', 'not recorded')}\n\n"
    out += _section("Scope and verification", str(record.get("scope", "Scope not recorded.")))
    out += _section("Source notes", str(record.get("notes", "No source notes are recorded.")))
    out += _section(
        "Important limitation",
        "A source lead is not the same as a verified program rule. Never infer program eligibility, "
        "closing merit, fees, active application dates, or campus availability from a source title alone. "
        "If status is unverified, partially verified, stale, or conflicting, state that explicitly and "
        "use the official URL above for confirmation.",
    )
    return out.strip() + "\n"


def _build_university_text(university: dict[str, Any]) -> str:
    sources = university.get("sources", []) or []
    source_lines = "\n".join(
        f"- {s.get('url', '(no url)')} (last verified {s.get('last_verified', '(unknown)')})"
        for s in sources
    ) or "- (no sources listed)"

    programs = university.get("programs", []) or []
    program_lines = "\n".join(
        f"- {p['name']} ({p['id']}, {p.get('duration', '(unknown)')})" for p in programs
    ) or "- (no programs listed)"

    out = f"# {university['name']} — Overview\n\n"
    out += f"Full name: {university.get('full_name', university['name'])}.\n"
    out += f"Location: {university.get('location', '(unknown)')}.\n"
    out += f"Website: {university.get('website', '(not listed)')}.\n\n"
    out += _section("Description", university.get("description", "") or "")
    out += _section("Programs Offered", program_lines)
    out += _section("Sources and Verification", source_lines)
    out += _section(
        "Disclaimer",
        university.get("disclaimer", "")
        or "Admission policies change. Always confirm critical details on the official university website before applying.",
    )
    return out.strip() + "\n"


def synthesize_policy_files(
    universities_path: Path | None = None,
    policies_dir: Path | None = None,
) -> dict[str, Any]:
    """Read the JSON, write one .txt per program + one overview per university.

    Returns a manifest dict with generation metadata.
    """
    src = universities_path or UNIVERSITIES_PATH
    out_dir = policies_dir or POLICIES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    with src.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    metadata = data.get("metadata", {})
    written: list[dict[str, str]] = []

    for university in data.get("universities", []) or []:
        uid = university["id"]
        uni_dir = out_dir / uid
        uni_dir.mkdir(parents=True, exist_ok=True)

        overview_path = uni_dir / "overview.txt"
        overview_path.write_text(_build_university_text(university), encoding="utf-8")
        written.append(
            {
                "university_id": uid,
                "program_id": "overview",
                "path": str(overview_path.relative_to(out_dir.parent.parent)),
            }
        )

        for program in university.get("programs", []) or []:
            pid = program["id"]
            program_path = uni_dir / f"{pid}.txt"
            program_path.write_text(
                _build_program_text(program, university), encoding="utf-8"
            )
            written.append(
                {
                    "university_id": uid,
                    "program_id": pid,
                    "path": str(program_path.relative_to(out_dir.parent.parent)),
                }
            )

    # Add source-registry documents to RAG so a question about an institution
    # outside the six-university program dataset gets an explicit coverage answer
    # instead of unrelated results from another university.
    source_registry_path = Path(__file__).resolve().parents[1] / "app" / "data" / "admissions_sources.json"
    if source_registry_path.exists():
        with source_registry_path.open("r", encoding="utf-8") as handle:
            source_registry = json.load(handle)
        for source in source_registry.get("sources", []) or []:
            uid = str(source.get("university_id", "unknown"))
            source_id = str(source.get("source_id", "source"))
            safe_source_id = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in source_id)
            uni_dir = out_dir / uid
            uni_dir.mkdir(parents=True, exist_ok=True)
            source_path = uni_dir / f"official-source-{safe_source_id}.txt"
            source_path.write_text(_build_registry_source_text(source), encoding="utf-8")
            written.append({
                "university_id": uid,
                "program_id": f"official-source-{safe_source_id}",
                "path": str(source_path.relative_to(out_dir.parent.parent)),
            })

    manifest = {
        "generated_at": date.today().isoformat(),
        "source_file": str(src),
        "source_version": metadata.get("version", "unknown"),
        "source_last_updated": metadata.get("last_updated", "unknown"),
        "official_source_registry": str(source_registry_path),
        "files": written,
    }

    manifest_md = "# Policy Corpus Manifest\n\n"
    manifest_md += f"- Generated: {manifest['generated_at']}\n"
    manifest_md += f"- Source file: {manifest['source_file']}\n"
    manifest_md += f"- Source version: {manifest['source_version']}\n"
    manifest_md += f"- Source last updated: {manifest['source_last_updated']}\n\n"
    manifest_md += "## Files\n\n"
    for entry in written:
        manifest_md += f"- {entry['path']} (university={entry['university_id']}, program={entry['program_id']})\n"
    manifest_md += (
        "\nThese files are generated from `data/universities.json` plus the official-source registry at `backend/app/data/admissions_sources.json` and committed as "
        "the RAG retrieval corpus. To regenerate, run `python -m backend.rag.build_index`.\n"
    )
    (out_dir / "MANIFEST.md").write_text(manifest_md, encoding="utf-8")

    return manifest


if __name__ == "__main__":  # pragma: no cover
    result = synthesize_policy_files()
    print(f"Wrote {len(result['files'])} policy files.")
