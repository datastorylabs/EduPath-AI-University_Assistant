# EduPath frontend

This folder contains the React/Vite interface for the incremental EduPath rebuild. It is designed for a local hackathon demo and uses the FastAPI backend for authentication and data. It does not contain a second mock database or an authentication bypass.

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

The guided adviser is deterministic for now. It uses the saved profile, only current source-verified computing rules, and source citations. It is not a free-form chatbot and does not estimate admission probability. The catalogue is deliberately incomplete.

## Safety choices

- The frontend uses the backend's HttpOnly session cookie and CSRF token flow. It does not put session tokens, passwords, profiles, or conversation history in localStorage or sessionStorage.
- The CSRF token remains in React memory and is re-bootstrapped from the API when the page loads.
- React renders user and API content as text; no untrusted message is inserted with dangerouslySetInnerHTML or parsed as arbitrary HTML.
- External citations are only linked when their URL uses HTTP or HTTPS, and new tabs use rel=noopener noreferrer.
- There is no unauthenticated demo mode and no invented sample student record.
- The API URL must be a same-origin path or explicit HTTP(S) URL; non-local production API URLs must use HTTPS.
- Production should serve the SPA and API from the same site, preferably with a reverse proxy. The backend CORS allowlist and HTTPS cookie settings must match that deployment.

Before using real student data, finish the remaining platform work for private document storage/OCR, account-wide deletion and retention, and live production PostgreSQL/Redis verification.
