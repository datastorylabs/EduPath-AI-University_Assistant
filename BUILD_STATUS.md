# EduPath Rebuild — Build Status

**Last updated:** 2026-10-23  
**Working branch:** rebuild/phase-1-foundation  
**Baseline:** main at 5a36ccb76b722ff9f1f3fe5a7c95d100750478ff (Release EduPath AI v1.0.0, 2026-09-05)

## Phase 0 — Repository audit and plan: COMPLETE

- Inspected the linked filxxa/EduPath-AI repository through connected GitHub tools. Direct shell cloning failed because DNS resolution for github.com was unavailable, so the full legacy test suite could not be run locally.
- Confirmed a Streamlit multipage Python app with document validation/extraction/OCR, profile merging, a deterministic eligibility and merit engine, a university JSON catalog, and Chroma/Groq RAG modules.
- Catalog metadata says it covers six universities (FAST-NUCES, NUST, LUMS, COMSATS, UET Lahore, MUET), last updated 2026-09-04. Dataset notes require intake-specific official confirmation.
- A historical release report states 378 tests passed on 2026-09-05. This is a prior report, not an independent run during this rebuild.

## Phase 1 — Foundation: IMPLEMENTED; isolated verification passed

- Added a parallel FastAPI app under backend/app/, preserving the Streamlit UI and legacy modules.
- Added environment-backed settings, SQLAlchemy engine/session dependency, liveness/readiness health endpoints, the initial user schema, and Alembic migration.
- Added lightweight requirements-api.txt, .env.example, runtime exclusions, API tests, and setup/status documentation.
- Isolated verification: python -m pytest -q — 9 passed. Temporary SQLite migration reached 0001_initial_users (head); alembic check reported no new upgrade operations. Liveness/readiness returned HTTP 200.

## Phase 2 — Security and authentication: IMPLEMENTED; focused verification passed

- Added /auth/csrf, /auth/register, /auth/login, /auth/me, /auth/logout, and /auth/logout-all.
- Added Argon2id password hashing, normalized email inputs, generic login failures, opaque HttpOnly session cookies, server-side session/CSRF token digests, expiry/revocation checks, inactive-account rejection, and logout-all.
- Added CSRF double-submit checks for state-changing auth endpoints; the CSRF bootstrap preserves a matching token for an active session. Added an ownership helper that returns 404 for cross-user resources, input validation error sanitization, security headers, no-store auth responses, minimal audit events, and authentication rate limiting.
- Development/test uses a bounded in-process fixed-window limiter. Production requires rediss:// for shared rate limits and fails closed when Redis is unavailable; PostgreSQL, a strong secret, and HTTPS CORS allowlist are also required.
- Added Alembic migration 0002_auth_sessions_and_audit for sessions and security audit events.
- Verification: python -m pytest tests/api -q — 24 passed. Temporary SQLite migration reached 0002_auth_sessions_and_audit (head); alembic check reported no new upgrade operations. Schema tables verified: users, auth_sessions, security_audit_events, and alembic_version.

## Phase 3 — University research, deterministic eligibility, and conversational intent: IN PROGRESS

- The official-source registry now contains 14 source records across 11 Pakistani universities: FAST-NUCES, NUST, COMSATS, GIKI, LUMS, UET Lahore, MUET, NED, University of Karachi, the University of the Punjab, and IBA Karachi. Source records distinguish verified, partially verified, unverified, stale, and conflicting evidence. Registry coverage is not a claim that every program or campus has been researched.
- Added/expanded cycle-specific deterministic rules for 8 computing programs: FAST-NUCES BS AI, CS, Data Science, Cyber Security, and Software Engineering (2026); NUST BS AI, CS, and Data Science (2026–2027). These rules are tied to official eligibility pages and distinguish minimum eligibility from merit or admission probability.
- The source registry records the University of the Punjab 2026–27 vacant-seat phase as stale because its published application window (8–28 September 2026) has passed. NUST's published general NET merit weighting is recorded with a verified scope (75% NET, 10% SSC, 15% HSSC); this is not an admission-probability estimate.
- Added source metadata validation/stale-source detection and public catalogue APIs. Missing, unsupported, or expired rules remain indeterminate rather than being guessed.
- Improved backend/rag/prompter.py so the latest question is classified into a response contract and alternative-university questions override an earlier action plan. The rule-based fallback has catalog-based alternative lookup; tests cover the related path.
- Verification checkpoint: GitHub Actions run #16 at commit cd936d60122069e8fd884b1340d2bbc8eaf8e511 passed 53 tests with 2 deprecation warnings. Several smaller commits since then, including Phase 4, still require a fresh run.
- Research limitation: only FAST-NUCES and NUST currently have cycle-specific program rules enabled for deterministic evaluation. Other universities in the source registry still need program/campus/intake-specific rule extraction before their criteria can be safely evaluated automatically.

## Phase 4 — Persistent user-data storage: IMPLEMENTED; CI VERIFIED

- Added student_profiles, allowing each account to store one validated academic profile with qualification, SSC/HSSC marks, subjects, per-subject marks, and equivalency status.
- Added conversations and conversation_messages to persist conversation titles and user messages, with a service helper that can also persist internally generated assistant messages and citations when advisor integration is added.
- Added private endpoints: GET/PUT/DELETE /profile/me; POST /conversations; GET /conversations; GET /conversations/{id}; POST /conversations/{id}/messages; and DELETE /conversations/{id}.
- All profile and conversation lookups are scoped to the authenticated owner. State-changing endpoints require session-bound CSRF validation; personal-data responses set Cache-Control: no-store; audit entries exclude profile values and message content.
- Added Alembic migration 0003_profiles_and_conversations, validation schemas, tests for persistence, user isolation, validation, and deletion, and SQLite foreign-key enforcement.
- Verified by GitHub Actions run #51 (push) and run #52 (pull request) against code commit `6be03578fc7cbf7d1918fd294c4d5eeb9bc5e562`: fresh SQLite migration reached `0003_profiles_and_conversations (head)`, `alembic check` reported `No new upgrade operations detected`, and the API/source/conversation test job passed `59 tests, 2 warnings`. This verifies the branch checkpoint's lightweight test/migration pipeline; it is not a production deployment or live PostgreSQL/Redis test.
- Scope limits: student profiles are not yet consumed by the eligibility endpoint or RAG advisor; assistant replies are not yet automatically generated or stored from the current UI; no document/file storage or OCR persistence is included; full account deletion and retention automation remain outstanding.

## Phase 5 — Safe React frontend and guided adviser integration: IMPLEMENTED; CI VERIFIED AT CODE CHECKPOINT

- Added a React/Vite workspace with a responsive dashboard, authentication, academic-profile editor, programme explorer/eligibility checker, guided advisor sessions, and conversation history.
- Connected the UI to the API through a same-origin /api development proxy. The React app uses the backend's HttpOnly session cookie and CSRF flow; the CSRF token remains in memory and is re-bootstrapped from the API.
- No profile, password, session token, or conversation history is written to localStorage/sessionStorage. User/API content is rendered as React text, not injected HTML; citations require HTTP(S) URLs and open in a protected new tab.
- Added a deterministic, owner-scoped profile-to-programme check endpoint that loads the saved profile, evaluates only currently source-verified computing rules, and persists both the user request and cited result atomically. This is not open-ended LLM chat and makes no admission-probability claims.
- Added frontend setup and deployment guidance, strict static-host security headers, and a Node-based production build job in GitHub Actions. Verified by GitHub Actions run #91 at code checkpoint `bb749bb983674492950e5b7ad361a6295429be42`: the React/Vite production build passed; a fresh SQLite database migrated to `0003_profiles_and_conversations (head)`; `alembic check` reported `No new upgrade operations detected`; and the API/admissions/advisor suite passed 62 tests with 2 warnings. The subsequent build-status edit is documentation-only and is newer than this verified code checkpoint.
- Limitations: original Streamlit UI remains separate; frontend has no document-upload UI/private document storage; full account deletion and retention workflow are still outstanding. Prefer same-site production hosting/reverse proxy because auth cookies currently use SameSite=Lax.

## Phase 6 — Account deletion and user data control: IMPLEMENTED

- Added DELETE /auth/account with an explicit current-password confirmation, CSRF validation against the active session, and a bounded destructive-action rate limit. Failed password confirmation leaves the account and saved data intact.
- The deletion transaction removes the account's conversation messages, conversations, academic profile, active/revoked auth sessions, and user row. Existing audit records lose their account foreign-key link through the database's SET NULL relationship; a minimal deletion event is written without a user identifier. Cookies are cleared and the response is no-store.
- Added the matching profile-screen danger zone with an explicit confirmation dialog and current-password field. On success, the frontend clears in-memory profile/history/session state and returns to the sign-in screen.
- Added API tests for missing CSRF, unauthenticated calls, failed password confirmation, successful deletion, removal of dependent rows, and the unlinked audit event. Check CI against the updated branch head before treating this checkpoint as verified.
- Remaining privacy work: private file/document storage and OCR, a defined retention policy and automation for security audit metadata, and live production PostgreSQL/Redis verification. No real student documents should be uploaded to a public demo.

## Known blockers and risks

- Email verification, password recovery, MFA, account administration, and frontend authentication integration are not implemented.
- Academic profile and conversation endpoints now have owner-scoped queries and dedicated tests; private document CRUD/storage endpoints are still absent.
- The Streamlit application is not integrated with the new API authentication boundary or Phase 4 profile/conversation storage.
- Redis and PostgreSQL have not been tested as live production services. Rate limiting is currently IP-based; deployments must configure trusted proxies correctly and review broader abuse prevention.
- Private document storage, retention/deletion policy and automation, and real production PostgreSQL/Redis verification remain incomplete.
- Current official-source admissions research is incomplete. The source registry is not evidence that every listed institution has verified program rules for the 2026–27 cycle.
- The linked filxxa/EduPath-AI is read-only for this connected account. Changes are staged on a separate branch in the writable synchronized copy datastorylabs/EduPath-AI-University_Assistant; no main branch or original repository has been changed.

## Next task — Phase 7: private-document boundary and retention

Define a documented privacy/retention policy and implement private document storage/OCR only behind authenticated owner-scoped routes, file size/type validation, malware-scanning hooks, and deletion/retention controls. Keep document bytes out of logs, public web paths, and model prompts unless the student explicitly authorizes a safe extraction workflow. Continue to verify SQLite migrations in CI and exercise PostgreSQL/Redis in a separate staging environment before production use.
