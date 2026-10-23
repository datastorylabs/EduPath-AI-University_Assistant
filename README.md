# EduPath AI

EduPath is a Pakistan-specific university admissions assistant. The original Streamlit multipage interface is the primary application. It combines academic document upload, OCR/text extraction, editable profile fields, university/program data, deterministic eligibility and merit calculations, an admissions RAG advisor with a rule-based fallback, and an action plan.

EduPath is a guidance tool, not an official university decision. Students must confirm criteria, intake cycles, deadlines, and fees with the university.

## Run locally (Windows)

Requirements: Python 3.11+, Git, and Tesseract OCR with the English language pack for scanned images/PDFs. Start in the repository root.

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
~~~

Create a local environment file and a unique development secret:

~~~powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
~~~

Open .env and replace the placeholder SECRET_KEY with the generated value. Keep .env private. Set GROQ_API_KEY in .streamlit/secrets.toml (copy .streamlit/secrets.toml.example) or in the environment to enable the Groq-backed RAG advisor. Without a valid key, EduPath uses its deterministic/rule-based fallback where supported.

Apply database migrations, then start the API in Terminal 1:

~~~powershell
alembic -c backend/alembic.ini upgrade head
python -m uvicorn backend.app.main:app --reload
~~~

Keep Terminal 1 open. Start the original Streamlit interface in Terminal 2 from the repository root:

~~~powershell
.\.venv\Scripts\Activate.ps1
streamlit run Home.py
~~~

Open the local URL Streamlit prints, normally http://localhost:8501. The UI authenticates against the local database and persists each signed-in user's application snapshot. The API and Streamlit process must use the same .env/database settings.

## Security and persistence

- Accounts use Argon2id password hashing and revocable server-side sessions; the raw session token is held in Streamlit server-side session state, not browser storage.
- Each account's profile, selected program, extracted structured fields, labels, and advisor history are persisted in a user-owned database row.
- Original uploaded files are validated, stored under random server-generated names in a private per-account directory outside the web root, and never committed to Git. Sign-out clears in-memory application state; account deletion removes the account's private upload directory and saved database records.
- Upload validation checks supported extensions, file size, and file signatures. OCR is bounded and reports when Tesseract is unavailable or extraction quality is insufficient; OCR output must be reviewed before relying on it.
- Eligibility decisions are deterministic and based on the bundled catalog. Missing or estimated data must not be treated as official eligibility.
- The RAG advisor retrieves university policy text and displays source labels when available. If the LLM or retrieval system is unavailable, it falls back to rule-based answers; it does not guarantee admissions outcomes.
- Local file storage is suitable for development and controlled demos. Before public deployment, add malware scanning, encrypted storage/backups, a documented retention policy, secure reverse-proxy/TLS configuration, and operational monitoring. Do not upload real student records to a public demo until those protections are in place.

## Data and limitations

The catalog includes six universities, but source-verified cycle-specific deterministic rules are only enabled for selected FAST-NUCES and NUST computing programmes. RAG policy coverage varies by institution/program and is only as current as the bundled source files. The Groq-backed advisor requires your own API key; no key is included in the repository.

The private upload directory defaults to data/private_uploads/ and can be moved by setting EDUPATH_PRIVATE_STORAGE_DIR to a private persistent disk location. Ensure that directory is backed up and never exposed by a static web server.

## Verification

~~~powershell
python -m pytest tests/api tests/test_legacy_storage.py tests/test_private_documents.py tests/test_ocr.py tests/test_pipeline.py tests/test_conversational_advisor.py -q
alembic -c backend/alembic.ini current
alembic -c backend/alembic.ini check
~~~

See BUILD_STATUS.md for the latest verification checkpoint and remaining production limitations.
