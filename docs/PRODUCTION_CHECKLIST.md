# Production checklist and known gaps

**Status:** nothing in this repository has been deployed, and most of it has never been executed (see [TEST_REPORT.md](../TEST_REPORT.md)). Treat the first deployment as a **staging** run. Work through section A in order; section E lists what has never been verified and section F what is not implemented.

## A. Before the first deploy (in this order)

1. **Run everything locally and fix what breaks** — none of this has been run yet:
   `cd backend && pip install -r requirements-dev.txt && pytest -x && ruff check . && alembic upgrade head` ·
   `cd frontend && npm install && npm test && npm run lint && npm run build` · `npm run e2e:install && npm run e2e` ·
   `python backend/tools/check_repo.py && python backend/tools/check_docs.py && python backend/tools/check_names.py`.
2. **Commit lockfiles.** `npm install` creates `frontend/package-lock.json`; commit it. Dependency versions in `backend/requirements.txt` and `frontend/package.json` were pinned from memory and never installed — expect to adjust a pin. Then `pip-audit -r backend/requirements.txt` and `npm audit`.
3. **Install and commit the font.** `cd frontend && npm run fonts:install`, then commit `frontend/public/fonts/`. (Vercel's build runs the same script, but GitHub's unauthenticated API limits can make that download fail; a committed file avoids it. Without the file headings fall back to a monospace font.)
4. **Commit your logo** at `frontend/public/brand/synaxys-logo.svg` (black artwork; it is inverted in dark mode).
5. **Add what the repository lacks:** a `LICENSE`, a security contact in [SECURITY.md](../SECURITY.md), and — if this is a public product — a privacy policy and terms (code is processed by OpenAI and stored as snippets in Pinecone; customers must be told).
6. **Create the GitHub App** ([GITHUB_SETUP.md](GITHUB_SETUP.md)). Production callback URL = `https://YOUR-FRONTEND-DOMAIN/api/v1/auth/github/callback` (the *frontend* domain); webhook URL = the *direct* API URL `https://YOUR-API-HOST/api/v1/webhooks/github`. Permissions: Contents read, Metadata read, Pull requests read/write. Install it only on the repositories you want reviewed.
7. **OpenAI and Pinecone** ([PINECONE_OPENAI.md](PINECONE_OPENAI.md)): a project API key with a monthly spending limit; a *serverless* Pinecone index, metric cosine, dimension = `EMBEDDING_DIMENSIONS` (1536).
8. **Generate secrets** (commands in [SECURITY.md](../SECURITY.md)): `APP_SECRET_KEY`, `ENCRYPTION_KEY`, `GITHUB_WEBHOOK_SECRET`. The **same** values must be set on the API *and* the worker. Keep the GitHub App `.pem` outside git.
9. **Database:** managed PostgreSQL with automated backups. Run `alembic upgrade head` against a **staging** Postgres first (it has only ever been written for SQLite-tested models, never executed). Never run `python -m app.db.seed` on a production database.
10. **Deploy the API and the worker** ([DEPLOYMENT.md](../DEPLOYMENT.md), `render.yaml`). The worker is mandatory — without it webhooks are accepted but no review, indexing or publishing ever runs. On Render a worker is a paid instance type.
11. **Deploy the frontend to Vercel** (project root `frontend`). First edit `frontend/vercel.json`: replace `REPLACE-WITH-YOUR-RENDER-SERVICE.onrender.com` with your API host, otherwise every API call fails.
12. **Smoke-test** (section C), then connect one real repository and open a test PR.

## B. Production values that must be exactly right

| Variable | Value |
|---|---|
| `APP_ENV` | `production` (the app refuses to start if the guards in SECURITY.md fail) |
| `COOKIE_SECURE` | `true` |
| `FRONTEND_URL`, `CORS_ORIGINS` | your frontend origin, e.g. `https://app.example.com` (no trailing slash) |
| `BACKEND_URL` | the **direct** API URL (shown to admins as the webhook URL) |
| `GITHUB_REDIRECT_URI` | `https://<frontend domain>/api/v1/auth/github/callback` — must equal the App's callback URL exactly |
| `TRUST_PROXY_HEADERS` | `true` only when all traffic arrives through proxies you control |
| `REVIEW_USE_MOCK_LLM` | `false`; `OPENAI_API_KEY` set |
| `VECTOR_BACKEND` | `pinecone`; `EMBEDDING_DIMENSIONS` equals the index dimension |
| `DATABASE_URL` | PostgreSQL (`postgres://…` is accepted and normalised) |
| `DEMO_LOGIN_ENABLED` | irrelevant in production (always off) — leave `false` |

## C. Smoke test after deploying

1. `GET /api/v1/health` → `{"status":"ok"}`; `GET /api/v1/health/ready` → database reachable, integration flags true.
2. Open the frontend → **Continue with GitHub** → you land on the dashboard (an endless login loop means the cookie/rewrite setup is wrong: see TROUBLESHOOTING).
3. **Settings → Integrations**: every row *Configured*; webhook URL matches the GitHub App.
4. GitHub App → Advanced → Recent deliveries: *Redeliver* a `ping` → HTTP 200 `pong`; a wrong secret → 401.
5. Sync repositories → connect one → open a PR → a review appears (worker running) → approve a comment → publish → it appears on GitHub as a comment-only review.
6. *Index code* → status *indexed* → Code Search returns results scoped to that repository.
7. Sign out → you are on the login page and a reload does not sign you back in.

## D. Operating it

* **Monitoring:** uptime check on `/api/v1/health/ready`; ship stdout logs (JSON) to a log service; alert if the worker stops (there is no external heartbeat monitor outside Docker's health check). There are no metrics, tracing or error-tracking integrations (e.g. Sentry).
* **Failed jobs** have no admin screen. Inspect them in the database: `select id, kind, status, attempts, last_error from background_jobs where status = 'failed' order by id desc limit 50;`
* **Backups:** enable them and *test a restore* (the database holds reviews, drafts, audit logs and the job queue; Pinecone can be rebuilt by re-indexing).
* **Retention:** nothing is deleted automatically, so these tables grow forever: `user_sessions`, `webhook_deliveries`, `background_jobs`, `audit_logs`, `review_posting_attempts`. Schedule your own cleanup (for example expired `user_sessions`, `webhook_deliveries` older than 30 days, finished `background_jobs` older than 30 days) and test it on staging first.
* **Cost:** OpenAI spending limit; tune `REVIEW_MAX_FILES`, `REVIEW_TOTAL_CHARS`, `INDEX_MAX_FILES`; remember indexing embeds every changed chunk.
* **Scaling:** run **one** API instance (rate limits are in memory per process). More workers are fine in principle (`SKIP LOCKED`) but untested.
* **Updates:** deploy order is migrations → API → worker. Future schema changes must be real Alembic migrations (`alembic revision --autogenerate`, reviewed by hand): the baseline `0001` creates tables from the current models.
* **Secret rotation:** see SECURITY.md (`python -m app.scripts.rotate_keys` for `ENCRYPTION_KEY`).

## E. Never verified (NOT RUN)

pytest (67 API/DB tests), Vitest (all frontend test files), ESLint, `vite build`, Playwright, Ruff, Alembic on any database (SQLite *or* PostgreSQL), `pip-audit`/`npm audit`, Docker image builds and Compose, the CI workflow, Render and Vercel configs, the Geist Pixel font download, and every call to GitHub (OAuth, App tokens, webhooks, tree/blob/PR/comment APIs), OpenAI (structured output, embeddings) and Pinecone (upsert/list/query/delete). Also unverified: how the UI looks and animates in real browsers, mobile layout, and accessibility.

## F. Not implemented / known gaps

**Features**
* Related-PR navigation from search results; a branch selector in the search UI (the API accepts a branch; only the default branch is indexed).
* Dismissing a finding independently of its comment; cancelling a *queued* review from the UI/API (the queue supports it, no endpoint exposes it).
* Deleting or editing already-published GitHub comments; undoing a publish.
* Partial indexing of huge repositories (GitHub-truncated trees are refused).
* Teams/workspaces as a concept (access is per user, derived from GitHub permissions); email/Slack notifications; account deletion and data export; an admin UI for failed jobs and webhook deliveries.
* Deterministic scanners (SAST, dependency, secret scanning) are not integrated; AI review quality is not measured.
* Cross-file context is mentioned in the review summary but retrieved snippets are not shown in a panel.

**Hardening and operations**
* No shared (multi-instance) rate limiter; the request-size limit only reads `Content-Length` (also set a body limit at your proxy).
* No Content-Security-Policy header (only `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`); check that your host sends `Strict-Transport-Security`, or add it in `frontend/vercel.json`.
* No favicon, social/OG meta tags or `robots.txt`.
* No Python lock file with hashes; no `package-lock.json` until you create it.
* `backend/app/middleware` is an empty package (security headers and size limit live in `main.py`); delete it or move that code there.
* Repository roles are refreshed only when a user presses *Sync from GitHub*; GitHub App user tokens expire (about 8 h), after which sync asks the user to sign in again.

**Legal / product**
* No licence, security contact, privacy policy, terms of service or data-processing terms; customers must consent to their code being processed by OpenAI and indexed in Pinecone. Publishing the App publicly on GitHub has its own listing requirements.
