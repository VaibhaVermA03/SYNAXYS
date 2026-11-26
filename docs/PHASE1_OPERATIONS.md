# Phase 1 operations guide (rate limiting, Sentry, admin, cleanup, CSP, scanning)

Status labels: everything here is **implemented**; nothing has been run against real Redis, Sentry, Render or Vercel by the author
(see `IMPLEMENTATION_STATUS.md` for what was executed).

## 1. Distributed rate limiting (Redis)
Code: `backend/app/core/rate_limit.py`, `backend/app/core/redis_client.py`, `backend/app/api/deps.py`, `backend/app/api/router.py`.

| Setting | Default | Meaning |
|---|---|---|
| `REDIS_URL` | empty | Empty = per-process memory limiter (**correct only with one API instance**). `redis://` or `rediss://` (TLS). Treat as a secret (may contain a password) |
| `RATE_LIMIT_REDIS_FAILURE` | `memory` | While Redis is unreachable: `memory` = per-process fallback (limits still apply, per instance), `closed` = deny requests, `open` = allow |
| `RATE_LIMIT_REDIS_TIMEOUT_SECONDS` | 0.25 | Connect/read timeout. Keep small: it is paid by a request when Redis hangs |
| `RATE_LIMIT_REDIS_RETRY_SECONDS` | 15 | Circuit breaker: after a failure Redis is not contacted for this long |
| `RATE_LIMIT_KEY_PREFIX` | `synaxys:rl` | Change when several environments share one Redis |
| `GLOBAL_RATE_LIMIT_PER_MINUTE` | 300 | Per client IP, every API route except health and the GitHub webhook |
| `USER_RATE_LIMIT_PER_MINUTE` | 240 | Per authenticated user (cannot be dodged by changing IP) |
| `TRUSTED_PROXY_HOPS` | 0 | See "Client IP" below |

**Algorithm.** One MULTI/EXEC transaction per check: `SET key 0 EX window NX`, `INCR key`, `TTL key`. The counter and its expiry are created
together, so a key can never live forever. Fixed windows: around a window boundary a client can send up to 2x the limit once.

**Policies** (route-specific limits keep their existing IP keys and values): auth login/callback/demo 10/min, code search 30/min, repository
sync 6/min, indexing 6/min, manual review 20/min, publish 10/min, rule test 10/min, admin job retry 30/min per user. The GitHub webhook has
**no IP limit on purpose** (GitHub delivers from a small shared set of addresses; it is protected by HMAC verification and the size cap).

**Production requirements for Redis**
* Same region as the API; private/internal URL if the host offers one; TLS (`rediss://`) and a password if it is reachable from the internet.
* `maxmemory-policy volatile-lru` (counters all carry a TTL). Do **not** use `noeviction` (writes would start failing when full).
* No persistence or replication needed: losing the data only resets counters. A few MB is plenty.
* Give the **API and the worker** the same environment variables (the worker does not rate limit, but keeping env identical avoids drift).
* Verify after deploy: `GET /api/v1/health/ready` returns `"rate_limiter": "redis"`. `"memory"` = `REDIS_URL` empty; `"memory-fallback"` = Redis configured but currently failing (an error is logged once per outage; only the exception type is logged).

**Client IP.** Limits are keyed on the client address. With `TRUST_PROXY_HEADERS=false` only the TCP peer is used (behind a proxy that is the
proxy's address: everyone shares one bucket). With `true` and `TRUSTED_PROXY_HOPS=0` the **first** `X-Forwarded-For` entry is used (correct when
the edge, e.g. Vercel, overwrites the header; spoofable on any path that reaches the API directly). `TRUSTED_PROXY_HOPS=N` takes the N-th entry
from the right: direct-to-Render traffic is `1`; Vercel -> Render is `2`. These topologies are **unverified**: check the real header on a test
request before relying on it. The per-user limit does not depend on this.

## 2. Sentry
Code: `backend/app/core/monitoring.py` (API + worker), `frontend/src/lib/monitoring.js`. You need **two** Sentry projects (Python/FastAPI and React/browser).

| Where | Variable | Notes |
|---|---|---|
| Backend (API + worker) | `SENTRY_DSN`, optional `SENTRY_ENVIRONMENT` (defaults to `APP_ENV`), `SENTRY_RELEASE` (e.g. git SHA), `SENTRY_TRACES_SAMPLE_RATE` (0.0) | Empty DSN = disabled |
| Frontend (build time) | `VITE_SENTRY_DSN`, `VITE_SENTRY_ENVIRONMENT`, `VITE_APP_RELEASE` | Set in Vercel project settings; rebuild after changing |

A DSN is a public identifier, not a secret. **Never sent:** request bodies, cookies, headers, query strings (OAuth `code`/`state`), local variables,
source lines, user email/IP/name (only the numeric user id), anything matching token/key/secret/password patterns; messages are truncated to 500 characters.
Captured: unhandled API errors, 5xx upstream failures (GitHub/OpenAI/Pinecone) with an error-code tag, final background-job failures (tags `job_id`,
`job_kind`), cleanup failures, database-connectivity failures on `/api/v1/health/ready`, UI render crashes and unhandled browser errors.
Grouping: GitHub API errors group by status code, upstream errors by error code, job failures by kind + exception type.
Test the backend: `python -c "from app.core.config import get_settings; from app.core.monitoring import init_monitoring, capture_exception; import sentry_sdk; init_monitoring(get_settings(), 'api'); capture_exception(RuntimeError('sentry test'), area='manual_test'); sentry_sdk.flush(5)"`.
Frontend CSP: `connect-src` allows `*.ingest.sentry.io` (and `.us.`/`.de.`); once the region is known, replace the wildcards with your exact ingest host.

## 3. Platform administrators
`ADMIN_GITHUB_IDS=12345,67890` - **numeric** GitHub user ids (`https://api.github.com/users/<login>` -> `id`), not logins. Empty = nobody. The check runs in the
backend on every `/api/v1/admin/*` request (`require_admin` in `backend/app/api/deps.py`); non-admins get 404. The sidebar link ("Job Monitor", `/app/admin/jobs`)
is only a convenience. The seeded demo user can never be an admin. The screen reads the real `background_jobs` table: filters (status, type), pagination, stats,
details with an id-only payload allow-list and the already-redacted error summary (no stack traces). Retry = atomic `failed -> queued` (a double click or two
admins re-queue once; the second gets 409), resets the linked review/indexing row in the same transaction, and writes an `admin.job_retry` audit entry.

## 4. Automatic cleanup and retention
Code: `backend/app/services/retention.py`, `backend/app/services/retention_policy.py`, scheduled by `backend/app/workers/runner.py`.

| Data | Deleted when | Setting (days) |
|---|---|---|
| Sessions | expired or revoked longer ago than | `RETENTION_SESSIONS_DAYS` 7 (active sessions are never touched) |
| Webhook deliveries | received longer ago than | `RETENTION_WEBHOOK_DAYS` 30 (minimum 7: it is also the replay-recognition window) |
| Jobs succeeded/cancelled | finished longer ago than | `RETENTION_JOBS_DONE_DAYS` 14 |
| Jobs failed | finished longer ago than | `RETENTION_JOBS_FAILED_DAYS` 60 |
| Indexing jobs | finished longer ago than; the newest per repository is kept | `RETENTION_INDEXING_JOBS_DAYS` 30 |
| Audit log (general) | older than; 0 = forever | `RETENTION_AUDIT_DAYS` 365 |
| Audit log (security: `auth.*`, `admin.*`, `github.credentials*`, `account.*`, `workspace.*`, `security.*`) | older than; 0 = forever | `RETENTION_SECURITY_AUDIT_DAYS` 730 |

Never deleted: queued/processing jobs, repositories, findings, reviews, comments, posting attempts, `indexed_branch_files`, `branch_index_states`. Expired invitations, export files and
tokens do not exist yet; their rules are added with the features that create them. Batches of `CLEANUP_BATCH_SIZE` (500), at most `CLEANUP_MAX_BATCHES` (20)
per rule per run; the rest is picked up next run. Idempotent. One rule failing does not stop the others. A `system.cleanup` audit row records counts when something was deleted.

**Scheduling.** The worker starts a cleanup about 60 s after boot and then every `CLEANUP_INTERVAL_MINUTES` (60) on its own thread; a PostgreSQL advisory lock
prevents two workers cleaning at once. This only works while the worker process is running. On a host that sleeps or does not keep the worker alive
(for example Render free instances) schedule it externally: a Render **Cron Job** (or any scheduler that can run your image) with the same environment as the API and the command
`python -m app.scripts.cleanup` (use `--dry-run` first: it only counts). Exit code 1 = a rule failed. Set `CLEANUP_ENABLED=false` on the worker if you do this, to avoid double runs.

## 5. Security headers and CSP
* API (`backend/app/core/security_headers.py`): `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; ...`, `X-Content-Type-Options`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, `Permissions-Policy`, `Cache-Control: no-store`, `Strict-Transport-Security: max-age=31536000` (only when `APP_ENV=production` and `COOKIE_SECURE=true`;
  deliberately without `includeSubDomains`/`preload`, which are hard to undo). Dev-only `/docs` is exempt from the CSP.
* SPA: `frontend/vercel.json` (production on Vercel) and `frontend/nginx.conf` (Docker). The CSP is **Report-Only** until you have checked the real deployment.
* The inline theme script moved to `frontend/public/theme-init.js` so `script-src 'self'` needs no `'unsafe-inline'`/nonce. `style-src 'self'` works because React sets styles through the DOM API.

| Directive | Value | Why |
|---|---|---|
| `default-src` | `'self'` | baseline |
| `script-src`, `style-src`, `font-src`, `manifest-src`, `worker-src` | `'self'` | everything is bundled/self-hosted (fonts in `frontend/public/fonts`) |
| `img-src` | `'self' data: https://avatars.githubusercontent.com` | GitHub profile pictures |
| `connect-src` | `'self'` + Sentry ingest hosts | `/api` is same-origin through the rewrite/proxy |
| `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, `frame-ancestors 'none'` | | hardening |

**Rollout.** 1) Deploy. 2) In Chrome DevTools open every page (login, OAuth round trip, dashboard, repositories, PR + review detail, search, rules, settings, admin) with the Console visible; every
`[Report Only] Refused to ...` line is something the enforcing policy would break. 3) Fix or allow-list it, redeploy. 4) Rename the header `Content-Security-Policy-Report-Only` to
`Content-Security-Policy` in both `frontend/vercel.json` and `frontend/nginx.conf` (and add `; upgrade-insecure-requests` if you want it). 5) Re-test the same pages. The GitHub OAuth sign-in is a full-page redirect, which `connect-src` does not affect; it is the first thing to re-test.

## 6. Security scanning (`.github/workflows/security.yml`, `.github/dependabot.yml`, `.gitleaks.toml`)
* **Semgrep** (SAST; rule sets `p/python`, `p/javascript`, `p/react`, `p/owasp-top-ten`): reports everything as an artifact; only `ERROR` severity fails the build. Tests and e2e are excluded.
* **Gitleaks** (secrets, full git history). Free for personal accounts; an organisation needs a `GITLEAKS_LICENSE` secret. Allow-list only documented placeholders in `.gitleaks.toml`.
* **Dependabot**: weekly PRs for pip, npm, GitHub Actions, Docker; **major** versions are never proposed automatically.
* **pip-audit / npm audit** stay in `ci.yml` (dependency vulnerabilities) - no second dependency scanner was added.
* No secrets are used; the workflow never uses `pull_request_target`, so fork code never runs with privileged credentials.

Handling findings: *critical/high or any secret* - fix before merge; a leaked secret is rotated first, history cleanup second (see `docs/KEY_ROTATION.md`). *medium* - fix or open an issue within the sprint.
*low/info* - review weekly. A false positive is suppressed in code with `# nosemgrep: <rule-id>` plus a one-line reason, never by disabling the rule set. Pin the actions and the Semgrep image to commit SHAs/digests when you can look them up.
