# EduPath AI

EduPath is a Pakistan-specific university admissions decision-support project. It combines academic document extraction, editable student-profile fields, structured university/program data, deterministic eligibility and merit calculations, admission checklists, and a retrieval-grounded advisor. It is not an official university decision or a replacement for the current university admissions portal.

## Current project state

The existing application is a Streamlit multipage prototype. Its useful logic is being preserved while a separate FastAPI foundation is introduced incrementally. **The API foundation is not yet a production-ready replacement for the Streamlit app.**

The source baseline inspected for this rebuild is the September 5, 2026 Release EduPath AI v1.0.0 commit. A historical report in the repository states that 378 tests passed at that time; this rebuild has not independently rerun the complete legacy test suite.

## Existing Streamlit application

The current entry point is Home.py; its multipage UI is in pages/. Existing backend/ modules cover document validation/OCR, profile management, eligibility, merit calculations, and the RAG advisor. University data lives in data/universities.json; retrieval policy text is in data/policies/.

To run the existing UI using its legacy dependency set:

~~~bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run Home.py
~~~

Scanned document OCR requires a compatible local Tesseract installation. Never use real student documents in a public demo environment.

## FastAPI foundation, authentication, and storage

The new API lives under backend/app/ alongside the legacy modules; it does not replace the existing Streamlit entry point yet.

Phase 1 added environment-driven settings, SQLAlchemy engine/session support, Alembic migrations, health endpoints, and a lightweight API dependency file.

Phase 2 added:
- Registration and login with Argon2id password hashing and input validation.
- Opaque server-side sessions; raw session tokens are placed only in an HttpOnly cookie, while token digests are stored in the database.
- Session expiration, revocation, logout-all, and inactive-account rejection.
- Double-submit CSRF validation for login, registration, logout, and logout-all.
- Generic login failures, sanitized 422 errors that do not echo rejected input, and no-store headers for auth routes.
- Basic security headers, low-PII security audit events, and authentication rate limits.
- A process-local fixed-window rate limiter for development/test. Production configuration requires a TLS-protected Redis URL for shared limits and fails closed if Redis is unavailable.

Phase 4 is in progress and adds:
- An optional academic profile persisted per signed-in user, with validation for marks, qualification, subjects, subject marks, and equivalency status.
- Private conversation records and ordered user-message history stored in the database.
- Owner-scoped list/read/write/delete operations. A foreign user's record is returned as not found rather than exposing that it exists.
- No-store response headers for personal profiles and conversation history, plus low-PII audit events for profile/conversation changes.
- Alembic migration 0003_profiles_and_conversations. SQLite foreign-key enforcement is enabled for local development.

**Current storage limitation:** saved profiles are not yet automatically loaded into the existing RAG advisor or eligibility endpoint. User messages can be saved, but the frontend and advisor are not yet wired together to generate and persist assistant replies. Uploaded files/OCR output, retention automation, whole-account deletion, and production database validation remain future work.

The session cookie is HttpOnly; the CSRF cookie is intentionally readable by frontend JavaScript so it can be returned in the X-CSRF-Token header. Cookies use SameSite=Lax, with Secure enabled in production. Production also requires PostgreSQL, a non-placeholder secret of at least 32 characters, and explicit HTTPS CORS origins.

### Install and run the API

Install API dependencies:

~~~bash
python -m pip install -r requirements-api.txt
~~~

Copy .env.example to .env. Local development defaults to SQLite. From the repository root, apply all database migrations before running the API:

~~~bash
alembic -c backend/alembic.ini upgrade head
python -m uvicorn backend.app.main:app --reload
~~~

Local endpoints:
- GET /health/live and GET /health/ready — liveness and database readiness.
- GET /auth/csrf, POST /auth/register, POST /auth/login, GET /auth/me, POST /auth/logout, and POST /auth/logout-all — authentication/session endpoints.
- GET /profile/me, PUT /profile/me, and DELETE /profile/me — read, create/replace, or delete the signed-in user's academic profile.
- POST /conversations, GET /conversations, GET /conversations/{id}, POST /conversations/{id}/messages, and DELETE /conversations/{id} — private conversation metadata and user-message history.
- /admissions/catalog, /admissions/universities, /admissions/sources, /admissions/rules, /admissions/evaluate, and /admissions/compare — public admissions catalogue and decision-support APIs.

State-changing authenticated endpoints require the CSRF token returned by the signed-in session and sent in the X-CSRF-Token header. Interactive API docs are available at /docs in non-production mode only.

Tests and migrations:

~~~bash
python -m pytest tests/api -q
alembic -c backend/alembic.ini current
alembic -c backend/alembic.ini check
~~~

## Security limitations — not production-ready

Phase 2 is foundational authentication, not a complete security certification. Email verification, password recovery, MFA, account administration, and frontend login integration are not implemented. Registration currently returns a conflict for duplicate email addresses; account enumeration protection requires a broader email-verification flow and is not claimed here. Academic profiles and conversations are now owner-scoped in the API, but uploaded documents still have no private API storage boundary. Redis/PostgreSQL production services have not been exercised in this environment. Login rate limiting is currently IP-based; production deployments must configure trusted proxies correctly, and broader abuse controls should be reviewed.

Private document storage, malware scanning, document retention/deletion, whole-account deletion, trusted-proxy configuration, and the Streamlit-to-API trust boundary remain future work. Do not use real student documents in a public demo until those protections exist.

## University data status

The current catalog metadata identifies six universities—FAST-NUCES, NUST, LUMS, COMSATS University Islamabad, UET Lahore, and MUET—and records 2026-09-04 as its last update. The rebuild source registry has leads for more universities, but only FAST-NUCES and NUST currently have the selected cycle-specific computing rules enabled for deterministic evaluation. The requested rule-by-rule, official-source-verified national dataset is not yet complete.

See BUILD_STATUS.md for phase checkpoints, verification results, and remaining blockers.
