# EduPath AI

EduPath is a Pakistan-specific university admissions decision-support project. It combines academic document extraction, editable student-profile fields, structured university/program data, deterministic eligibility and merit calculations, admission checklists, and a retrieval-grounded advisor. It is not an official university decision or a replacement for the current university admissions portal.

## Current project state

The existing application is a Streamlit multipage prototype. Its useful logic is being preserved while a separate FastAPI foundation is introduced incrementally. **The API foundation is not yet a production-ready replacement for the Streamlit app.**

The source baseline inspected for this rebuild is the September 5, 2026 `Release EduPath AI v1.0.0` commit. A historical report in the repository states that 378 tests passed at that time; this rebuild has not independently rerun the complete legacy test suite.

## Existing Streamlit application

The current entry point is `Home.py`; its multipage UI is in `pages/`. Existing `backend/` modules cover document validation/OCR, profile management, eligibility, merit calculations, and the RAG advisor. University data lives in `data/universities.json`; retrieval policy text is in `data/policies/`.

To run the existing UI using its legacy dependency set:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run Home.py
```

Scanned document OCR requires a compatible local Tesseract installation. Never use real student documents in a public demo environment.

## FastAPI foundation and security checkpoint

The new API lives under `backend/app/` alongside the legacy modules; it does not replace the existing Streamlit entry point yet.

Phase 1 added environment-driven settings, SQLAlchemy engine/session support, initial Alembic migrations, health endpoints, and a lightweight API dependency file.

Phase 2 added:
- Registration and login with Argon2id password hashing and input validation.
- Opaque server-side sessions; raw session tokens are placed only in an HttpOnly cookie, while token digests are stored in the database.
- Session expiration, revocation, logout-all, and inactive-account rejection.
- Double-submit CSRF validation on login, registration, logout, and logout-all.
- Generic login failures, sanitized 422 errors that do not echo rejected input, and no-store headers for auth routes. CSRF bootstrap preserves the bound token for a live session rather than invalidating it on page load.
- Basic security headers, low-PII security audit events, and authentication rate limits.
- A process-local fixed-window rate limiter for development/test. Production configuration requires a TLS-protected Redis URL for shared limits and fails closed if Redis is unavailable.

The session cookie is HttpOnly; the CSRF cookie is intentionally readable by frontend JavaScript so it can be returned in the `X-CSRF-Token` header. Cookies use `SameSite=Lax`, with `Secure` enabled in production. Production also requires PostgreSQL, a non-placeholder secret of at least 32 characters, and explicit HTTPS CORS origins.

### Install and run the API

Install API dependencies:

```bash
python -m pip install -r requirements-api.txt
```

Copy `.env.example` to `.env`. Local development defaults to SQLite. From the repository root:

```bash
alembic -c backend/alembic.ini upgrade head
python -m uvicorn backend.app.main:app --reload
```

Local endpoints:
- `GET http://127.0.0.1:8000/health/live` — process liveness.
- `GET http://127.0.0.1:8000/health/ready` — database readiness.
- `GET http://127.0.0.1:8000/auth/csrf` — obtain the initial CSRF cookie/token.
- `POST /auth/register` and `POST /auth/login` — send JSON plus `X-CSRF-Token` matching the CSRF cookie.
- `GET /auth/me` — current session identity.
- `POST /auth/logout` and `POST /auth/logout-all` — revoke sessions with the session-bound CSRF token.

Interactive API docs are available at `/docs` in non-production mode only.

Tests and migrations:

```bash
python -m pytest tests/api -q
alembic -c backend/alembic.ini current
alembic -c backend/alembic.ini check
```

## Security limitations — not production-ready

Phase 2 provides foundational authentication, not a complete security certification. Email verification, password recovery, MFA, account administration, and a frontend login integration are not implemented. Registration currently returns a conflict for duplicate email addresses; preventing account enumeration requires an email-verification flow and is not claimed here. No private document/profile CRUD endpoints have yet been wired to the owner-checking helper, so per-resource isolation must be added and tested before storing personal documents. Redis/PostgreSQL production services have not been exercised in this environment. Login rate limiting is currently IP-based; production deployments must configure trusted proxies correctly, and a broader abuse-control policy should be reviewed.

Private document storage, retention/deletion, account-data deletion, malware scanning, and the Streamlit-to-API trust boundary remain future work. Do not use real student documents in a public demo until those protections exist.

## University data status

The current catalog metadata identifies six universities—FAST-NUCES, NUST, LUMS, COMSATS University Islamabad, UET Lahore, and MUET—and records `2026-09-04` as its last update. The requested 10+ university, rule-by-rule, official-source-verified dataset is not yet complete.

See [`BUILD_STATUS.md`](BUILD_STATUS.md) for phase checkpoints, verification results, blockers, and the next task.
