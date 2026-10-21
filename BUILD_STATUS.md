# EduPath Rebuild — Build Status

**Last updated:** 2026-10-22  
**Working branch:** `rebuild/phase-1-foundation`  
**Baseline:** `main` at `5a36ccb76b722ff9f1f3fe5a7c95d100750478ff` (Release EduPath AI v1.0.0, 2026-09-05)

## Phase 0 — Repository audit and plan: COMPLETE

- Inspected the linked `filxxa/EduPath-AI` repository through connected GitHub tools. Direct shell cloning failed because DNS resolution for github.com was unavailable, so the full legacy suite could not be run locally.
- Confirmed a Streamlit multipage Python app with document validation/extraction/OCR, profile merging, a deterministic eligibility and merit engine, a university JSON catalog, and Chroma/Groq RAG modules.
- Catalog metadata says it covers six universities (FAST-NUCES, NUST, LUMS, COMSATS, UET Lahore, MUET), last updated 2026-09-04. Dataset notes require intake-specific official confirmation.
- No `BUILD_STATUS.md`, FastAPI app, SQLAlchemy persistence layer, or Alembic scaffold existed at inspected paths.
- A historical release report states 378 tests passed on 2026-09-05. This is a recorded prior report, not an independent run during this rebuild.

## Phase 1 — Foundation: IMPLEMENTED; isolated verification passed

- Added a parallel FastAPI app under `backend/app/`, preserving the Streamlit UI and legacy modules.
- Added environment-backed settings, production configuration checks, SQLAlchemy engine/session dependency, liveness/readiness health endpoints, initial user schema, and Alembic migration.
- Added lightweight `requirements-api.txt`; legacy `requirements.txt` remains unchanged.
- Added `.env.example`, runtime exclusions, API tests, and setup/status documentation.
- Isolated verification: `python -m pytest -q` — 9 passed. Applied migration to temporary SQLite; `alembic current` showed `0001_initial_users (head)`; database contained `users` and `alembic_version`. `alembic check` reported no new upgrade operations. Liveness/readiness returned HTTP 200 in the isolated workspace.

## Known blockers and risks

- Authentication endpoints, password hashing, session issuance/revocation, CSRF strategy, recovery, and authorization are not implemented. The user table is schema groundwork only.
- Private document storage, retention/deletion, account deletion, and per-user authorization remain unimplemented.
- University rules have not been re-audited against current official 2026–27 admission sources. Research for 10+ universities remains incomplete.
- The Streamlit app has not been migrated behind an authenticated API boundary. Do not use real student documents in a public demo or treat this phase as production-ready.
- The linked `filxxa/EduPath-AI` is read-only for this connected account. Changes are on a separate branch in the writable synchronized copy `datastorylabs/EduPath-AI-University_Assistant`; no `main` branch or original repository was changed.

## Next task — Phase 2: Security and authentication

Implement Argon2id password hashing, authentication/session lifecycle, CSRF protection appropriate to the selected browser auth mechanism, rate limiting, security headers, structured audit events, authorization tests, and safe error handling.
