# Optional React/Vite API demo

The primary EduPath interface is the original Streamlit application. From the repository root, install `requirements.txt`, apply `alembic -c backend/alembic.ini upgrade head`, and run `streamlit run Home.py`. This folder contains an optional React/Vite interface for testing the FastAPI APIs; it does not contain a mock database or an authentication bypass.

## Run locally

Use Node.js 22.12 or newer and Python 3.11 or newer.

Start the API from the repository root in a first terminal:

~~~bash
python -m pip install -r requirements-api.txt
~~~

Create .env from the root .env.example, then run the migrations and API:

~~~bash
alembic -c backend/alembic.ini upgrade head
python -m uvicorn backend.app.main:app --reload
~~~

Open a second terminal:

~~~bash
cd frontend
npm install --ignore-scripts --no-audit --no-fund
npm run dev
~~~

Open the local Vite address shown in the terminal (normally http://localhost:5173). The frontend calls /api, which Vite proxies to http://127.0.0.1:8000; that keeps local API requests same-origin in the browser. Do not open the frontend using a different hostname unless its origin and proxy configuration are adjusted.

For a production bundle:

~~~bash
npm run build
npm run preview
~~~

The output is written to dist/. Set VITE_API_BASE_URL to /api when a reverse proxy serves the frontend and routes /api/* to the FastAPI backend. This same-site deployment is the preferred setup because the API currently uses SameSite=Lax cookies. Do not weaken the cookie settings just to make a cross-site deployment work; configure the frontend/API hosting arrangement first.

## Included demo flow

- Register or sign in.
- Create and edit a saved academic profile.
- Explore the currently source-verified programme rules and check minimum eligibility.
- Create a private review session and run a guided programme match or eligibility-gap check.
- Reopen and delete saved sessions.
- Permanently delete the account and owned saved data from the profile screen after confirming the current password.

The guided adviser is deterministic for now. It uses the saved profile, only current source-verified computing rules, and source citations. It is not a free-form chatbot and does not estimate admission probability. The catalogue is deliberately incomplete.

## Safety choices

- The frontend uses the backend's HttpOnly session cookie and CSRF token flow. It does not put session tokens, passwords, profiles, or conversation history in localStorage or sessionStorage.
- The CSRF token remains in React memory and is re-bootstrapped from the API when the page loads.
- React renders user and API content as text; no untrusted message is inserted with dangerouslySetInnerHTML or parsed as arbitrary HTML.
- External citations are only linked when their URL uses HTTP or HTTPS, and new tabs use rel=noopener noreferrer.
- There is no unauthenticated demo mode and no invented sample student record.
- The API URL must be a same-origin path or explicit HTTP(S) URL; non-local production API URLs must use HTTPS.
- Production should serve the SPA and API from the same site, preferably with a reverse proxy. The backend CORS allowlist and HTTPS cookie settings must match that deployment.

The primary Streamlit state snapshot retains structured profile and extraction fields/status, selected program, and advisor history. Uploaded file bytes and raw OCR text are not persisted. Before public use, configure live PostgreSQL/Redis, Tesseract on the actual target host, a valid Groq key/model, private original-file storage if required, recovery/MFA, and a documented retention policy.
