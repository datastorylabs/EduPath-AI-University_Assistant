# EduPath AI

EduPath is a Pakistan-specific university admissions decision-support project. It combines academic document extraction, editable student-profile fields, structured university/program data, deterministic eligibility and merit calculations, admission checklists, and a retrieval-grounded advisor. It is not an official university decision or a replacement for the university's current admissions portal.

## Current project state

The existing application is a Streamlit multipage prototype. Its useful logic is being preserved while a separate FastAPI foundation is introduced incrementally. **The API foundation is not yet a production-ready replacement for the Streamlit app.** Authentication, per-user authorization, secure document storage, and other security phases remain unfinished.

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

## New FastAPI foundation

The API lives under `backend/app/` alongside the legacy modules; it does not replace the existing Streamlit entry point yet.

Install the lightweight API dependencies:

```bash
python -m pip install -r requirements-api.txt
```

Copy `.env.example` to `.env`. Local development defaults to SQLite. From the repository root run:

```bash
alembic -c backend/alembic.ini upgrade head
python -m uvicorn backend.app.main:app --reload
```

Local endpoints:

- `GET http://127.0.0.1:8000/health/live` — process liveness.
- `GET http://127.0.0.1:8000/health/ready` — database readiness.
- `GET http://127.0.0.1:8000/docs` — development API docs (disabled in production mode).

API tests and migration verification:

```bash
python -m pytest tests/api -q
alembic -c backend/alembic.ini current
```

Production configuration requires a non-placeholder secret, PostgreSQL connection URL, and explicit HTTPS CORS origin allowlist. Do not place credentials in source control. Configuration validation is not a substitute for the Phase 2 security implementation.

## University data status

The current catalog metadata identifies six universities—FAST-NUCES, NUST, LUMS, COMSATS University Islamabad, UET Lahore, and MUET—and records `2026-09-04` as its last update. The catalog contains unknown/null fields where information was unavailable and tells users to verify each intake against the official portal. The requested 10+ university, rule-by-rule, official-source-verified dataset is not yet complete.

## Security and maturity warning

- The `users` table is schema groundwork only. No registration, login, or session endpoints are implemented in Phase 1.
- Private document storage, retention/deletion, account-data deletion, CSRF protections, and per-user authorization remain pending.
- Health checks prove only process/database availability, not end-to-end admissions workflows.
- The Streamlit app has not yet been moved behind the new authentication boundary.
- Do not claim student documents are production-protected until the relevant controls are implemented and tested.

See [`BUILD_STATUS.md`](BUILD_STATUS.md) for phase checkpoints, verification results, blockers, and the next task.
