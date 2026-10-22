# EduPath Rebuild — Build Status

**Last updated:** 2026-10-22  
**Working branch:** `rebuild/phase-1-foundation`  
**Baseline:** `main` at `5a36ccb76b722ff9f1f3fe5a7c95d100750478ff` (Release EduPath AI v1.0.0, 2026-09-05)

## Phase 0 — Repository audit and plan: COMPLETE

- Inspected the linked `filxxa/EduPath-AI` repository through connected GitHub tools. Direct shell cloning failed because DNS resolution for github.com was unavailable, so the full legacy test suite could not be run locally.
- Confirmed a Streamlit multipage Python app with document validation/extraction/OCR, profile merging, a deterministic eligibility and merit engine, a university JSON catalog, and Chroma/Groq RAG modules.
- Catalog metadata says it covers six universities (FAST-NUCES, NUST, LUMS, COMSATS, UET Lahore, MUET), last updated 2026-09-04. Dataset notes require intake-specific official confirmation.
- A historical release report states 378 tests passed on 2026-09-05. This is a prior report, not an independent run during this rebuild.

## Phase 1 — Foundation: IMPLEMENTED; isolated verification passed

- Added a parallel FastAPI app under `backend/app/`, preserving the Streamlit UI and legacy modules.
- Added environment-backed settings, SQLAlchemy engine/session dependency, liveness/readiness health endpoints, the initial user schema, and Alembic migration.
- Added lightweight `requirements-api.txt`, `.env.example`, runtime exclusions, API tests, and setup/status documentation.
- Isolated verification: `python -m pytest -q` — 9 passed. Temporary SQLite migration reached `0001_initial_users (head)`; `alembic check` reported no new upgrade operations. Liveness/readiness returned HTTP 200.

## Phase 2 — Security and authentication: IMPLEMENTED; focused verification passed

- Added `/auth/csrf`, `/auth/register`, `/auth/login`, `/auth/me`, `/auth/logout`, and `/auth/logout-all`.
- Added Argon2id password hashing, normalized email inputs, generic login failures, opaque HttpOnly session cookies, server-side session/CSRF token digests, expiry/revocation checks, inactive-account rejection, and logout-all.
- Added CSRF double-submit checks for state-changing auth endpoints; the CSRF bootstrap preserves a matching token for an active session. Added an ownership helper that returns 404 for cross-user resources, input validation error sanitization, security headers, no-store auth responses, minimal audit events, and authentication rate limiting.
- Development/test uses a bounded in-process fixed-window limiter. Production requires `rediss://` for shared rate limits and fails closed when Redis is unavailable; PostgreSQL, a strong secret, and HTTPS CORS allowlist are also required.
- Added Alembic migration `0002_auth_sessions_and_audit` for sessions and security audit events.
- Verification: `python -m pytest tests/api -q` — 24 passed. Temporary SQLite migration reached `0002_auth_sessions_and_audit (head)`; `alembic check` reported no new upgrade operations. Schema tables verified: `users`, `auth_sessions`, `security_audit_events`, and `alembic_version`.

## Phase 3 — University research and deterministic eligibility: PARTIALLY IMPLEMENTED; verification pending

- Added `backend/app/data/admissions_sources.json`, a structured discovery registry covering ten Pakistani universities: FAST-NUCES, NUST, COMSATS, GIKI, LUMS, UET Lahore, MUET, NED, University of Karachi, and University of the Punjab.
- Registry records distinguish `partially_verified` from `unverified`; inclusion in the registry does not certify program-level rules. Initial official-source checks identified the FAST-NUCES undergraduate eligibility page, NUST undergraduate eligibility and merit pages, and MUET admission policy. The other institutions remain source-discovery entries requiring further review.
- Added `backend/app/services/admissions_rules.py`, a deterministic fail-closed evaluator that returns eligible, ineligible, or indeterminate; it checks explicitly configured marks, subjects, qualification, and admission cycle. It does not use an LLM and does not estimate admission probability.
- Added `backend/app/services/admissions_sources.py` for metadata validation and stale-source detection.
- Added `tests/api/test_admissions_rules.py` for exact thresholds, below-threshold marks, missing data/subjects, qualification mismatch, unverified rules, cycle mismatch, invalid percentages, and source staleness.
- **Verification status:** These new Phase 3 files were written to the GitHub working branch, but the new tests have not yet been executed in a local runtime. Do not treat Phase 3 as complete until imports, JSON parsing/schema validation, test execution, and integration with the existing catalog have been verified.
- Existing `data/universities.json` has not been overwritten. The new source registry is a separate additive artifact pending a reviewed migration into the existing catalog schema.

## Next task — Phase 3 completion checkpoint

Run the API tests including `tests/api/test_admissions_rules.py`; validate `backend/app/data/admissions_sources.json`; audit the existing eligibility engine and catalog before integration; then research the ten institutions' current official prospectuses and encode specific program/campus/cycle rules only where evidence supports them. Resolve any test failures before marking Phase 3 complete.

## Known blockers and risks

- Email verification, password recovery, MFA, and account administration are not implemented.
- The ownership helper is groundwork only: each future document/profile endpoint must use owner-scoped queries and dedicated user-isolation tests. No private document CRUD routes exist yet.
- The Streamlit application is not integrated with the new API authentication boundary.
- Redis and PostgreSQL were not tested as live production services. Rate limiting is currently IP-based; deployments must configure trusted proxies correctly and review broader abuse prevention.
- Private document storage, retention/deletion, and account-data deletion remain incomplete.
- Current official-source admission research for 10+ universities has not been completed. Phase 3's source registry includes ten institutions, but only initial general-page checks have been made for a subset; do not represent this as ten universities fully researched or their program rules verified for the 2026–27 cycle.
- The linked `filxxa/EduPath-AI` is read-only for this connected account. Changes are staged on a separate branch in the writable synchronized copy `datastorylabs/EduPath-AI-University_Assistant`; no `main` branch or original repository has been changed.

## Next task — Phase 3: University research and deterministic eligibility

Audit the existing catalog schema; add structured official-source provenance, publication/admission cycle, verification date/status, and rule-level versioning; research at least 10 universities from official admissions sources; implement deterministic evaluation and tests for boundary marks, missing subjects, equivalency, conflicts, and unsupported rules. Never label unreviewed rules as verified.
