# SYNAXYS — Smarter Reviews. Safer Code.

AI-assisted code review and pull-request intelligence for GitHub: structured, evidence-backed review findings on a diff viewer, human-approved comment publishing, and semantic search over your codebase.

> **Project status — read this first.** This repository was generated in a sandbox **without internet access**, so dependencies could not be installed and **most of the code has never been executed**. What *was* executed is listed in [TESTING.md](TESTING.md) (99 dependency-free tests, syntax and import checks). Everything else — the full `pytest` suite, the frontend build and tests, Playwright, database migrations, Docker, and every call to GitHub, OpenAI and Pinecone — is **NOT RUN** and may contain bugs. Run the suites below on your machine and fix what they find before relying on it.

## What it does

| Area | Behaviour |
|---|---|
| Sign-in | GitHub OAuth (authorization code + PKCE S256 + signed state). Server-side sessions in HttpOnly cookies, CSRF protection, rate limits. |
| Repositories | Lists only repositories you can access through the GitHub App installation; admins enable reviewing per repository. |
| Reviews | Webhook / manual trigger → durable job → bounded AI review with structured findings. Every finding needs file, evidence quoted from the diff and a valid line (never invented). Labelled **AI suggestion**, never "confirmed". |
| Publishing | Comments are drafts. A repository admin edits/approves, then confirms publishing as a *comment-only* GitHub review. No duplicates; every attempt is recorded. Optional admin-enabled auto-publish. |
| Rules | Custom review rules (untrusted input, validated, wrapped as data) with a "test this rule" panel. |
| Search | Pinecone semantic code search, one namespace per repository, scoped to repositories you can access; also feeds cross-file context into reviews. |
| Ops | Settings/integration status page, audit trail, usage dashboard, health endpoints. |

Test report: [TEST_REPORT.md](TEST_REPORT.md) · **Go-live checklist and known gaps: [docs/PRODUCTION_CHECKLIST.md](docs/PRODUCTION_CHECKLIST.md)** · Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · API: [docs/API.md](docs/API.md) · Security: [SECURITY.md](SECURITY.md) · Deployment: [DEPLOYMENT.md](DEPLOYMENT.md) · GitHub setup: [docs/GITHUB_SETUP.md](docs/GITHUB_SETUP.md) · OpenAI/Pinecone: [docs/PINECONE_OPENAI.md](docs/PINECONE_OPENAI.md) · Problems: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

## What needs credentials

SYNAXYS signs people in **only through GitHub** — there is no sample-data or guest sign-in. To run it you need a GitHub App (free, about 10 minutes, see [docs/GITHUB_SETUP.md](docs/GITHUB_SETUP.md)).

| Feature | Needs |
|---|---|
| Start backend + frontend and see the login page | nothing |
| Sign in, sync repositories | GitHub App + OAuth credentials, `ENCRYPTION_KEY` |
| Real PR reviews, diffs of real PRs, publishing comments | GitHub App, `GITHUB_WEBHOOK_SECRET`, OpenAI, a running worker |
| Code search / indexing | GitHub App, OpenAI, Pinecone |
| "Test this rule" without OpenAI | `REVIEW_USE_MOCK_LLM=true` (labelled mock, **not AI**) — local development only |
| Seeded sample data | developer/test helper only: `python -m app.db.seed`, `DEMO_LOGIN_ENABLED=true`, then `POST /api/v1/auth/demo-login` (used by the optional real-backend e2e spec); always disabled in production |

Missing credentials always produce an explicit "not configured" message — never a fake success.

## Requirements

Python **3.12**, Node.js **20+** (22 was used), npm. PostgreSQL only for production (SQLite is the local default). Optional: ngrok (or similar) to receive GitHub webhooks locally.

## Quick start — macOS / Linux

```bash
# 1. Backend
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"                                  # -> APP_SECRET_KEY in .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"     # -> ENCRYPTION_KEY in .env
# set the GitHub / OpenAI values in .env as you obtain them (see "Using real GitHub, OpenAI and Pinecone" below)
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 2. Worker (second terminal, same venv) — runs reviews, indexing, publishing, cleanup
python -m app.workers.runner

# 3. Frontend (third terminal)
cd frontend
npm install
npm run dev                                             # http://localhost:5173
```

## Quick start — Windows PowerShell

```powershell
# 1. Backend
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"                                  # -> APP_SECRET_KEY in .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"     # -> ENCRYPTION_KEY in .env
# IMPORTANT on Windows: set WORKER_HEARTBEAT_PATH=worker.heartbeat in .env (the default is a Linux path)
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 2. Worker (new PowerShell window, venv activated)
python -m app.workers.runner

# 3. Frontend (new window)
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173> and choose **Continue with GitHub** (needs the GitHub App from [docs/GITHUB_SETUP.md](docs/GITHUB_SETUP.md)).

## Quick start — Docker Compose (full stack)

```bash
cp .env.example .env            # Windows PowerShell: Copy-Item .env.example .env   (this is the REPOSITORY-ROOT .env used by compose)
# edit .env: set APP_SECRET_KEY and ENCRYPTION_KEY (commands above); add GitHub/OpenAI/Pinecone values if you have them
docker compose up --build
```
Open <http://localhost:8080> (nginx serves the SPA and proxies `/api` to the API). Compose starts PostgreSQL (not published to the host), the API (also on `:8000`, e.g. for a webhook tunnel), the worker and the frontend; the API container runs `alembic upgrade head` on start. Compose **overrides** `DATABASE_URL`, `FRONTEND_URL`, `CORS_ORIGINS`, `BACKEND_URL`, `GITHUB_REDIRECT_URI` (= `http://localhost:8080/api/v1/auth/github/callback`, register that callback in your GitHub App) and `TRUST_PROXY_HEADERS`. The local database password defaults to a development value; set `POSTGRES_PASSWORD` in your shell to change it. Data lives in the `dbdata` volume (`docker compose down -v` deletes it). **This stack has never been run** (no Docker in the build sandbox).

## Using real GitHub, OpenAI and Pinecone

1. Create the GitHub App and OAuth credentials → [docs/GITHUB_SETUP.md](docs/GITHUB_SETUP.md). For local development set `GITHUB_REDIRECT_URI=http://localhost:8000/api/v1/auth/github/callback` and `FRONTEND_URL=http://localhost:5173`.
2. Create an OpenAI key and a Pinecone serverless index (cosine, dimension = `EMBEDDING_DIMENSIONS`, 1536 by default) → [docs/PINECONE_OPENAI.md](docs/PINECONE_OPENAI.md).
3. Put the values in `backend/.env` (every variable is documented in `.env.example`), restart the API and the worker.
4. Open **Settings → Integrations**: every integration should read *Configured*. Sign in with GitHub, press **Sync from GitHub**, connect a repository, open a pull request on it (webhooks need a public URL — see the ngrok section in the GitHub guide).

## Tests and checks

```bash
python backend/tools/run_pure_tests.py            # no installs needed; 99 tests (what was executed during generation)
cd backend && pytest                              # full backend suite (needs requirements-dev.txt)
cd frontend && npm test && npm run lint && npm run build
cd frontend && npm run e2e:install && npm run e2e # Playwright with a mocked API
python backend/tools/check_docs.py                # docs match settings, scripts and paths
python backend/tools/check_repo.py                # no secrets, required files, frontend<->backend route contract
python backend/tools/check_names.py               # undefined-name check (pyflakes F821 equivalent)
```
Details and the honest status table: [TESTING.md](TESTING.md).

## Repository layout

```
backend/app/        api/ (routers), core/ (config, security, encryption, logging), models/, schemas/, services/ (GitHub, diff, review,
                    publish, indexing, search, queue), agents/ (prompts, policies, review pipeline, LLM adapters), workers/, scripts/, tests/
backend/migrations/ Alembic (0001 baseline from model metadata, 0002 indexed_files)
backend/tools/      run_pure_tests.py, check_docs.py, check_repo.py, check_names.py, check_imports.py, gen_api_docs.py
frontend/src/       app/ (providers), components/, features/ (auth, dashboard, repositories, pull-requests, reviews, rules, code-search, settings), lib/, services/
frontend/e2e/       Playwright specs + stateful API mock
docs/               architecture, API, setup guides, troubleshooting
docker-compose.yml  backend/Dockerfile  frontend/Dockerfile  frontend/nginx.conf  .github/workflows/ci.yml
render.yaml  frontend/vercel.json   deployment configs (all unverified, see DEPLOYMENT.md)
```

## Branding, theme and fonts

* Logo: put your **black** SVG at `frontend/public/brand/synaxys-logo.svg`. It is shown next to the SYNAXYS wordmark and is inverted automatically in dark mode. Until it exists only the wordmark is shown — no logo is invented.
* Themes: dark `#d1d1d1 #828383 #434343 #2b2b2b #141414 #030303`, light `#e0ddd5 #c8c4b9 #aca49c #e7663e #69605f #33272b` (CSS variables in `frontend/src/styles/index.css`). Status colours (error/warning/success) and one darker orange for accent-coloured *text* are added because the palettes contain none.
* Font: headings, titles, header and sidebar use **Geist Pixel Circle** (SIL OFL 1.1). `npm run fonts:install` downloads it from the official `vercel/geist-font` repository into `frontend/public/fonts/` (it also runs before `npm run dev` / `npm run build`); commit the file afterwards. Without it the UI falls back to a monospace font.

## Licence

None is included. Add the licence you intend to use before distributing.
