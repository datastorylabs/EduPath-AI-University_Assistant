# EduPath — Final Integration Checkpoint

Updated: 2026-10-23  
Working branch: rebuild/phase-1-foundation  
Primary UI: Original Streamlit multipage interface (Home.py and pages/).

## Final integration work in this checkpoint

- Kept the original Streamlit UI and removed the newly added React/Vite frontend from this branch.
- Preserved the existing server-side account system with Argon2id password hashes, expiring/revocable sessions, login rate limiting, account deletion, and owner-scoped database records.
- Added the missing Alembic migration for streamlit_application_states, the per-user snapshot table already used by the original UI's persistence helpers.
- Added private per-account original-file storage. Validated uploads are saved with random server-generated names outside the web root; filenames are never used as storage paths. File metadata is persisted with the account snapshot, and uploads are rehydrated for that same account on a later session.
- Account deletion now attempts to remove the account's private original files as well as database records. Sign-out clears the current Streamlit session's application data immediately.
- Added tests for private upload round-trips, invalid file rejection, path traversal rejection, and account storage cleanup.
- Updated CI to verify the original Streamlit UI persistence helpers, private storage, OCR pipeline, advisor intent, API tests, clean SQLite migrations, and ORM schema drift.

## Existing features preserved

- Document upload, file signature/size validation, PDF text extraction, image/scanned-PDF OCR, structured field extraction, conflict-aware profile merging, and manual profile review.
- Deterministic eligibility/merit calculations and action-plan generation from the existing university catalog.
- Groq-backed retrieval-augmented admissions advisor with source labels and a rule-based fallback when the LLM/retrieval runtime is unavailable.
- Owner-scoped account/application-state persistence and private conversation records in the FastAPI database layer.

## Verification status

Changes have been committed to this branch. Do not consider the final checkpoint verified until the newly triggered GitHub Actions workflow completes successfully. The workflow runs:
- API/auth/admissions/persistence tests
- Legacy Streamlit state-snapshot tests
- Private file-storage tests
- OCR/pipeline and advisor tests
- Fresh SQLite migration and Alembic schema-drift checks

## Known limitations — not production certified

- A local Tesseract executable and English language pack are required for scanned-image/PDF OCR. OCR cannot guarantee correct extraction; students must review extracted fields.
- A valid Groq API key is required for the LLM-backed advisor. The fallback is deterministic and more limited than a general-purpose chat assistant.
- The bundled source registry/catalog is incomplete; cycle-specific deterministic computing rules are enabled only for selected FAST-NUCES and NUST programmes. Do not imply national coverage or admission probability.
- Private file storage is local disk by default, not encrypted object storage. Public deployment still needs malware scanning, encryption/backups, automated retention and purge, HTTPS/reverse-proxy review, trusted-proxy configuration, production PostgreSQL/Redis exercise, and monitoring.
- Original files are retained until the student removes them or deletes the account; a formal retention policy still needs to be defined.

## Local start commands

~~~powershell
python -m pip install -r requirements.txt
alembic -c backend/alembic.ini upgrade head
python -m uvicorn backend.app.main:app --reload
~~~

In a second terminal:

~~~powershell
.\.venv\Scripts\Activate.ps1
streamlit run Home.py
~~~
