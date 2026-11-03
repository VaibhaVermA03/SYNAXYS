# Deployment

> Before going live also work through **[docs/PRODUCTION_CHECKLIST.md](docs/PRODUCTION_CHECKLIST.md)** (what must be done, what has never been verified, and what is not implemented).

Target topology (as specified): **frontend on Vercel**, **API + worker on Render**, **managed PostgreSQL**, **Pinecone** cloud index, GitHub App. Nothing here has been deployed or verified; `render.yaml` and `frontend/vercel.json` were never applied. Do a staging deployment first.

```
Browser ──https──> Vercel (static SPA) ──/api/* rewrite──> Render web service (FastAPI) ──> PostgreSQL
GitHub  ──webhook (direct)────────────────────────────────> Render web service
Render worker (python -m app.workers.runner) ──> PostgreSQL (job queue), GitHub API, OpenAI, Pinecone
```

**Why the rewrite?** Sessions are `SameSite=Lax` HttpOnly cookies. If the browser called a different domain for the API, the cookie would be cross-site. Vercel therefore proxies `/api/*` to Render so the browser sees **one origin** and OAuth cookies land on the frontend domain.

## 1. Database
Create a PostgreSQL instance (Render Postgres or any managed Postgres) with backups enabled. `DATABASE_URL` may be given as `postgres://…`, `postgresql://…` or `postgresql+psycopg://…` (normalised automatically).

## 2. Pinecone and OpenAI
Follow [docs/PINECONE_OPENAI.md](docs/PINECONE_OPENAI.md): serverless index, cosine, dimension = `EMBEDDING_DIMENSIONS` (1536).

## 3. GitHub App
Follow [docs/GITHUB_SETUP.md](docs/GITHUB_SETUP.md). Production values:
* Homepage: `https://YOUR-VERCEL-DOMAIN`
* Callback URL (and `GITHUB_REDIRECT_URI`): **`https://YOUR-VERCEL-DOMAIN/api/v1/auth/github/callback`** (the frontend domain, through the rewrite)
* Webhook URL: **`https://YOUR-SERVICE.onrender.com/api/v1/webhooks/github`** (direct to the API; no cookies involved)
* Webhook secret = `GITHUB_WEBHOOK_SECRET`.

## 4. Render (API + worker)
Either apply `render.yaml` (Blueprint) or create the services by hand:

| | Web service | Background worker |
|---|---|---|
| Root directory | `backend` | `backend` |
| Build | `pip install -r requirements.txt` | same |
| Start | `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers` | `python -m app.workers.runner` |
| Health check | `/api/v1/health` (readiness incl. DB: `/api/v1/health/ready`) | none (heartbeat file; `python -m app.workers.runner --healthcheck` exits 0/1) |
| Python | 3.12 | 3.12 |

Environment (identical secrets on **both** services — notably `ENCRYPTION_KEY`, `APP_SECRET_KEY`, `DATABASE_URL`): everything in `.env.example`; at minimum `APP_ENV=production`, `DATABASE_URL`, `APP_SECRET_KEY`, `ENCRYPTION_KEY`, `COOKIE_SECURE=true`, `FRONTEND_URL=https://YOUR-VERCEL-DOMAIN`, `CORS_ORIGINS=https://YOUR-VERCEL-DOMAIN`, `BACKEND_URL=https://YOUR-SERVICE.onrender.com`, `GITHUB_*`, `GITHUB_WEBHOOK_SECRET`, `OPENAI_API_KEY`, `PINECONE_API_KEY`, `PINECONE_INDEX_NAME`, `EMBEDDING_DIMENSIONS`, `TRUST_PROXY_HEADERS=true`. The app refuses to start in production if the guards listed in [SECURITY.md](SECURITY.md) are violated — read the error in the deploy log.

Notes:
* A Render **background worker is a paid instance type**; without a worker, webhooks are accepted and queued but no review, indexing or publish job ever runs.
* Free web instances sleep; webhook deliveries to a sleeping instance may time out (GitHub lets you redeliver).
* Running migrations in the start command is simple but means every restart runs `alembic upgrade head`; use a pre-deploy command if your plan supports it.
* Rate limiting is per process — keep **one API instance** unless you add a shared limiter.

## 5. Vercel (frontend)
* Project root: `frontend`; framework preset Vite; build `npm run build`; output `dist`.
* Edit `frontend/vercel.json`: replace `REPLACE-WITH-YOUR-RENDER-SERVICE.onrender.com` with your API host. No environment variables are required (do **not** put secrets in `VITE_*`).
* The second rewrite sends all other paths to `index.html` (SPA routing).

## 6. Worker concurrency and queue
`WORKER_CONCURRENCY` (default 2) threads per worker process; more workers are safe on PostgreSQL (`FOR UPDATE SKIP LOCKED`, fenced completion) — unverified under real concurrency. Jobs retry with exponential backoff (15 s base, 15 min cap, `JOB_MAX_ATTEMPTS`=4); stale locks are recovered after the job timeout. Reviews that fail permanently are marked **failed** and can be retried from the UI.

## 7. Verify after deploying
1. `GET https://API/api/v1/health` → `{"status":"ok"}`; `/api/v1/health/ready` → DB reachable and integration flags.
2. Open the Vercel URL → **Continue with GitHub** completes and lands on the dashboard (if it loops back to login, see troubleshooting: cookies/rewrite).
3. **Settings → Integrations**: all items *Configured*; the displayed webhook URL matches GitHub's.
4. GitHub App → Advanced → recent deliveries: a `ping` shows HTTP 200 `pong`. A bad secret shows 401.
5. Sync repositories, connect one, open a PR → a review appears (needs the worker running).
6. Connect → *Index code* → status reaches *indexed* → Code Search returns results.

## 8. Logging, backups, recovery
Logs are JSON on stdout (secrets redacted best-effort) — ship them with your host's log drain. Enable automated Postgres backups and test a restore: the database is the system of record for reviews, drafts, audit logs and the job queue; Pinecone can be rebuilt by re-indexing. If the worker dies mid-job, the lease expires and another worker retries it; if the API dies, GitHub's webhook redelivery plus unique delivery IDs make replays safe. Rollback = redeploy the previous version; downgrade migrations only after reading them (`0002` is idempotent).

## 9. Docker
* `backend/Dockerfile` builds one image (Python 3.12, non-root user, health check on `/api/v1/health`) used for the API **and** the worker; `frontend/Dockerfile` builds the SPA and serves it with unprivileged nginx (`frontend/nginx.conf` proxies `/api/` to the `api` service and falls back to `index.html`).
* `docker-compose.yml` is a **local development** stack (PostgreSQL, API, worker, web). For production on a container host, build the two images, run the API with `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers`, run the worker with `python -m app.workers.runner`, give both the same environment (including `APP_ENV=production` and the guards in SECURITY.md) and a managed PostgreSQL; terminate TLS in front and proxy `/api` from the frontend origin.
* The worker image health check is `python -m app.workers.runner --healthcheck` (heartbeat file written every poll); give it a stop grace period longer than `WORKER_SHUTDOWN_GRACE_SECONDS` (30 s).
* None of the Docker files has been built or run.

## 10. CI
`.github/workflows/ci.yml` runs: backend (`pip check`, `ruff`, `pytest`, `alembic upgrade head`, `pip-audit`), frontend (lint, Vitest, build, `npm audit --audit-level=high`), Playwright e2e, repository checks (`run_pure_tests.py`, `check_docs.py`, `check_repo.py`, `check_names.py`, generated API reference up to date) and `docker compose build`. It needs no secrets. It has never run; the first run will likely need small fixes. Commit the `package-lock.json` created by your first `npm install` so CI can use `npm ci`.
