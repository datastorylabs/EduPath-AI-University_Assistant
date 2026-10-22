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

## Phase 3 — University research, deterministic eligibility, and conversational intent: IN PROGRESS

- The official-source registry now contains 14 source records across 11 Pakistani universities: FAST-NUCES, NUST, COMSATS, GIKI, LUMS, UET Lahore, MUET, NED, University of Karachi, the University of the Punjab, and IBA Karachi. Source records distinguish verified, partially verified, unverified, stale, and conflicting evidence. Registry coverage is not a claim that every program or campus has been researched.
- Added/expanded cycle-specific deterministic rules for 8 computing programs: FAST-NUCES BS AI, CS, Data Science, Cyber Security, and Software Engineering (2026); NUST BS AI, CS, and Data Science (2026–2027). These rules are tied to official eligibility pages and distinguish minimum eligibility from merit or admission probability.
- The source registry records the official University of the Punjab 2026–27 vacant-seat phase as stale because its published application window (8–28 September 2026) has passed. NUST's published general NET merit weighting is recorded with a verified scope (75% NET, 10% SSC, 15% HSSC); this is not an admission-probability estimate.
- Added backend/app/services/admissions_sources.py for source metadata validation and stale-source detection, plus backend/app/services/admissions_catalog.py to expose only rules whose source status, cycle, and freshness allow deterministic evaluation.
- Expanded backend/app/services/admissions_rules.py to evaluate qualification routes, separate SSC/HSSC thresholds, subject alternatives, explicitly conditional pathways, subject-level minima, IBCC equivalence, and cycle conflicts. Missing/unsupported/expired rules remain indeterminate rather than being guessed.
- Improved the conversational RAG prompt in backend/rag/prompter.py: the latest question is classified into a response contract, and alternative-university questions explicitly override an earlier action plan. The prompt directs the model to compare named options, use the academic profile, answer the concern first, and avoid generic 'register again' boilerplate. The rule-based fallback has a separate catalog-based alternative lookup; existing tests cover that path.
- Added tests for conversation intent, follow-up context, alternative retrieval, and profile-slice privacy. Updated catalogue assertions for the expanded eight-rule dataset.
- Verification: A prior CI run on the earlier eight-rule data commit exposed three stale assertions expecting two rules; these were updated to expect the expanded dataset and three NUST computing options for the 2026–27 comparison. A fresh workflow run is pending after the latest changes. Do not mark this phase complete until the latest workflow is green and the test suite has passed.
- Research limitation: the source registry covers 11 institutions, but only FAST-NUCES and NUST currently have cycle-specific program rules enabled for deterministic evaluation. COMSATS, GIKI, LUMS, UET Lahore, MUET, NED, University of Karachi, Punjab University, and IBA still need additional program/campus/intake-specific rule extraction before their criteria can be safely evaluated automatically.
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
