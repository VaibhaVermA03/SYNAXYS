# SYNAXYS — PROJECT_CONTEXT.md

Technical reference for restoring context in a future conversation. Written from a direct read of `SYNAXYS_clean_source.zip` (234 files) on 2026-11-19; **updated 2026-11-20 for Phase 1 (batch 13) Phase 2 (batch 14), Phase 3 (batch 15), Phase 4 (batch 16) and Phase 5 (batch 17)**. Sections marked *(Phase 1)* describe code that is written but has only been partly executed (see §17).
It is NOT a claim that the codebase is memorised: re-upload the changed files (or this file plus the files being edited) at the start of a new chat.

**Evidence labels used below:** `READ` = I read the code. `RAN` = I executed it. `NOT RUN` = not executed. Nothing in this file is "production verified".

---

## 1. Overview
SYNAXYS is an AI pull-request review SaaS ("Smarter Reviews. Safer Code."). Users sign in with GitHub OAuth, connect repositories through a GitHub App, and receive AI-generated findings on PR diffs. Findings become draft comments; a repository admin approves and publishes them to GitHub as one comment-only review. Repositories can be indexed into Pinecone for semantic code search and as cross-file context for reviews.

## 2. Stack (READ)
| Layer | Technology |
|---|---|
| Frontend | React 18.3, Vite, Tailwind 3.4, React Router, TanStack Query, react-hook-form + zod, Lucide; JavaScript/JSX; Vitest + Playwright |
| Backend | FastAPI, Starlette, SQLAlchemy 2 + Alembic, pydantic-settings, httpx |
| DB | PostgreSQL (prod), SQLite (dev/test) |
| Queue | Custom DB-backed queue (`background_jobs`), separate worker process (threads). No Celery |
| Rate limiting *(Phase 1)* | Redis (`redis` package) shared fixed-window counters; in-memory fallback |
| Error tracking *(Phase 1)* | Sentry (`sentry-sdk` backend, `@sentry/react` frontend), disabled without DSN |
| AI | OpenAI via LangChain (`langchain-openai`, structured output), model default `gpt-4o`; embeddings `text-embedding-3-small` (1536 dims) |
| Vector | Pinecone (`pinecone==5.4.2`), explicit in-memory adapter for dev/tests |
| Deploy | Vercel (frontend, `/api` rewritten to Render) + Render (API web service + paid background worker + Postgres); Docker Compose for local |
| CI | GitHub Actions `ci.yml` |

**Caveat:** several pinned versions (e.g. `fastapi==0.162.0`, `starlette==1.10.0`, `openai==3.45.0`, `cryptography==50.0.2`, `react-router-dom 7.18.5`, `zod 4.6.7`, `vitest 4.1.12`) could not be checked: my sandbox had no network. `IMPLEMENTATION_STATUS.md` itself says pins were chosen from memory. `NOT RUN`: `pip install`, `npm install`. No lockfile for Python; `frontend/package-lock.json` is present.

## 3. Folder structure (READ)
```
backend/
  app/main.py                 app factory, CORS, size guard, security headers (API only)
  app/core/                   config, security (HMAC, secret redaction, fingerprints), auth_tokens (signed state, CSRF, PKCE),
                              encryption (Fernet/MultiFernet), exceptions (error envelope), logging (JSON+redaction, request/job ids), db_url,
                              rate_limit (+DistributedLimiter, extract_client_ip), redis_client, monitoring (Sentry), security_headers, admin (ID allow-list)  [last 4 + redis: Phase 1]
  app/models/entities.py      all 19 tables (single file)
  app/db/                     base (UTCDateTime, TimestampMixin), session, seed (demo data)
  app/api/deps.py             session auth, CSRF, Origin check, rate_limit dependency
  app/api/v1/                 auth, github, repositories, pull_requests, reviews, review_actions, review_rules,
                              code_search, dashboard, settings, health, webhooks, admin (Phase 1)
  app/repositories/access.py  RepositoryAccess-based authorization helpers
  app/services/               github_service/github_http, webhook_service/webhook_events, job_queue/job_policy,
                              review_service/review_context/finding_validation/comment_service, publish_service/publish_logic,
                              indexing_service/index_policy/chunking/embedding_service/vector_service/context_retrieval/search_logic,
                              installation_service, auth_service, diff_service, rule_validation, integration_status,
                              admin_jobs + admin_policy, retention + retention_policy (Phase 1)
  app/agents/                 prompts, review_graph, llm (OpenAI + labelled mock), review_schemas, review_policies
  app/workers/                runner (thread pool, leases), registry, review_worker, publish_worker, indexing_worker
  app/tests/                  18 modules (pure + DB + API)
  migrations/versions/        0001_initial_schema (create_all from metadata), 0002_indexed_files
  app/scripts/                rotate_keys, cleanup (Phase 1)
  tools/                      check_docs/check_repo/check_names/check_imports/gen_api_docs/run_pure_tests/make_source_zip (Phase 1)
frontend/
  src/features/{auth,dashboard,repositories,pull-requests,reviews,code-search,rules,settings}
  src/components/{ui,layout,code-review,repositories}; src/lib/api.js (fetch client + CSRF); src/services/index.js
  nginx.conf, vercel.json, Dockerfile, e2e/ (Playwright with a hand-written mock API)
docs/, SECURITY.md, DEPLOYMENT.md, TESTING.md, README.md, render.yaml, docker-compose.yml, .github/workflows/ci.yml
```

## 4. Architecture and workflows (READ)
- **Request path:** browser → (Vercel rewrite or nginx) `/api/*` → FastAPI. Cookie session (`synaxys_session`, HttpOnly), CSRF token header on unsafe methods, Origin check.
- **Webhook path:** `POST /api/v1/webhooks/github`: size cap → HMAC-SHA256 on raw body (constant time) → header checks → JSON parse → `handle_delivery` in a threadpool. Idempotency via unique `webhook_deliveries.delivery_id`; a previously *failed* delivery is reprocessed on redelivery. Enqueue-only; no LLM in the request path.
- **Events handled:** `pull_request` (opened/synchronize/reopened/closed), `push` (default branch only → index job), `installation`, `installation_repositories`.
- **Review lifecycle:** webhook/manual → `CodeReview(queued)` + `BackgroundJob(kind=review, dedup_key=review:<review.dedup_key>)` → worker `handle_review` → diff fetched from GitHub with installation token → eligibility filter (binary/lockfile/generated/vendored/sensitive files excluded) → batches → LLM (structured output) → `finding_validation` (file must be in diff, evidence quote must occur literally, line range only if inside one hunk) → `ReviewFinding` + draft `ReviewComment` for verified inline locations → status `completed`. Older queued reviews of superseded commits are cancelled by the webhook handler.
- **Publish lifecycle:** admin approves (`draft→approved`), publish builds one `COMMENT`-only review with fingerprint markers `<!-- synaxys:fp=... -->`, re-lists existing GitHub comments to skip duplicates, per-comment `publishing` lock, 422 fallback to per-comment posting, every attempt in `review_posting_attempts` + `audit_logs`. Auto-publish is a per-repo opt-in that enqueues a `publish` job.
- **Phase 2 workflow (details `docs/PHASE2_WORKFLOW.md`):** finding dismissal is independent of comments (`finding_service.py`; columns `dismissed_by_id/at`, `dismiss_reason`, `dismiss_note`) and is carried across reviews of the same PR (fingerprint, or same file/category/title/evidence); queued-review cancel (`review_cancel.py`, atomic `job_queue.cancel`, `code_reviews.cancelled_by_id/at`); GitHub comment deletion (`comment_delete.py`: verify ownership, delete, re-fetch must be 404, state `deleted`, row kept); search hits carry a `pull_request` link built only from stored GitHub URLs (`review_workflow_logic.py`). Migration `0004_review_workflow`.
- **Finding status vs comment state:** `review_findings.status` = `open|dismissed|published`; `review_comments.state` = `draft|approved|published|failed|cancelled`; `code_reviews.status` = `queued|processing|completed|failed|cancelled`. (Before Phase 2 dismissal was only reachable by cancelling the comment; now `POST /reviews/{id}/findings/{fid}/dismiss|restore` exist.) Comment states now also include `deleted`.
- **Phase 3 indexing (current; details `docs/PHASE3_INDEXING.md`):** per-branch state (`branch_index_states`), per-file per-branch rows (`indexed_branch_files`, replaces `indexed_files`), persisted work units (`indexing_batches`), vector ids `<branchtag>:<pathhash>#<n>` in namespace `repo-<id>`, truncated trees walked directory by directory (`tree_walk.py`), `.gitignore` matcher (`gitignore.py`), priority-ranked file limit and batching (`index_policy.py`), job states `completed|partial|failed|cancelled`, continuation jobs for time slices, `index_branch_delete` job, per-repository include/exclude/max-files in `review_configurations`. Migration `0005`. The description below is the pre-Phase-3 flow, kept for history.
- **Indexing lifecycle (pre-Phase 3):** manual (`POST /repositories/{id}/index`, admin) or push webhook → `index` job → `run_index`: branch head → recursive tree (refuses if GitHub marks it `truncated`) → `plan_index` (exclusions, `index_max_files` cut-off after alphabetical sort, blob-SHA diff vs `indexed_files`) → delete removed files → per file: fetch blob → chunk → drop chunks containing secrets → embed → upsert → delete stale vector IDs → commit progress. Time budget 1700 s; job timeout 1800 s.
- **Search:** `POST /code-search/query` → repositories = RepositoryAccess ∩ enabled ∩ `index_status=indexed` (max 20) → embed query → one Pinecone query **per repo namespace** → `repo_id` re-checked in metadata → results carry repo, path, lines, branch, commit, snippet, GitHub blob permalink.

## 5. Database (READ; `backend/app/models/entities.py`)
users, oauth_identities (encrypted GitHub token), user_sessions (token hash), github_installations, repositories, repository_access (user↔repo, role `owner|member` derived from GitHub admin permission), review_configurations, review_rules, pull_requests, webhook_deliveries, background_jobs, code_reviews, review_findings, review_comments, review_posting_attempts, indexing_jobs, indexed_files, audit_logs. (alembic_version excluded.)
- **No workspace/organization/team/membership/invitation/notification/export tables exist.**
- Notable indexes/constraints: `background_jobs(status, run_after)`, `background_jobs.dedup_key` unique, `webhook_deliveries.delivery_id` unique, `review_findings(review_id, fingerprint)` unique, `indexed_files(repository_id, path)` unique, `code_reviews.dedup_key` unique.
- *(Phase 1)* Indexes added for cleanup: `user_sessions.expires_at`, `webhook_deliveries.received_at`, `background_jobs(status, finished_at)`, `audit_logs.created_at` (models + migration 0003).
- Migrations: 0001 is `create_all` from *current* metadata (so it is not a frozen schema); 0002 and 0003 are idempotent (skip what 0001's `create_all` already built). `NOT RUN`: alembic on any of them.

## 6. API (READ)
75 endpoints under `/api/v1` (39 original + 4 admin job endpoints (Phase 1) + 4 review-workflow endpoints (Phase 2): finding dismiss/restore, review cancel, GitHub comment delete + 4 Phase 3 endpoints: github-branches, index/retry-failed, branch index removal, code-search/branches; `POST .../index` and `index-status` gained a branch; + 24 Phase 4 endpoints for workspaces, notifications and account); authoritative generated list: `docs/API_ENDPOINTS.md` (regenerate with `python backend/tools/gen_api_docs.py`). Groups: auth (login, callback, me, logout, config, demo-login), github (installations, repositories list/sync/connect/disconnect/config, credentials revoke), pull-requests (list, detail, diff, review), reviews (list, detail, retry, approve, publish, comment patch, posting-attempts), review-rules (CRUD + test), repositories (index, index-status), code-search/query, dashboard, settings (integrations, audit), health, webhooks/github. Error envelope: `{"error": {"code", "message"}}`.

## 7b. Trust and compliance (Phase 5; `docs/PHASE5_TRUST.md`)
- Legal drafts with `[[placeholders]]` (nothing invented): single source `frontend/src/legal/{privacy,terms,security,license}.json`, shown publicly at `/legal/*`, Markdown + `docs/legal/PLACEHOLDERS.md` generated by `backend/tools/gen_legal_docs.py`; `LICENSE` is a proprietary notice; `SECURITY.md` starts with the vulnerability-reporting section (placeholder contacts); `docs/security.txt.template` is intentionally not published.
- Favicon set derived from `frontend/public/logo.svg` by `backend/tools/make_favicons.py`; head tags in `frontend/index.html`; `site.webmanifest`.
- `workspace_service.purge_repositories`: deleting a workspace (or the only member's account) deletes the repositories' reviews/findings/comments/index state; vectors go through an `index_delete` job with `purged: true`.

## 7a. Workspaces (Phase 4; details `docs/PHASE4_WORKSPACES.md`)
- Tables `workspaces`, `workspace_members` (owner|admin|member), `workspace_invitations` (GitHub login + hashed one-time token, 7 days), `notifications` (unique per user+dedup_key), `data_exports` (ZIP in DB, 24 h); `repositories.workspace_id`, `audit_logs.workspace_id`. Migration `0006`.
- **Authorization**: membership is the source of truth; `repository_access` is derived for workspace repositories (`workspace_service.sync_access`, invariant: exactly one row per member, role owner/admin -> `owner`, member -> `member`); GitHub-derived rows only for repositories outside any workspace. `workspace_service.require_member` guards workspace routes (404 for non-members, 403 for low roles). `deps.active_workspace` (`X-Workspace-Id`) verifies membership each request and only narrows lists.
- Services: `workspace_logic.py` (pure rules, legacy-access grouping, deletion identity check), `workspace_service.py`, `notification_service.py`, `account_service.py` (export + deletion); routers `workspaces.py`, `notifications.py`, `account.py`; worker kind `account_export`.
- Frontend: `WorkspaceProvider` + switcher in the header, notification bell/page, Workspaces page (members, invitations, activity, danger zone), invitation page, Account page (export/delete).

## 7. Authentication and authorization (READ)
- GitHub OAuth authorization-code + PKCE S256 + signed state cookie. Scope default `read:user`. User token stored Fernet-encrypted.
- Sessions: random token → SHA-256 hash stored; TTL `SESSION_TTL_HOURS` (12); expired/revoked rows are never deleted.
- CSRF: HMAC token derived from per-session secret, required on POST/PUT/PATCH/DELETE; plus Origin allow-list.
- Authorization model: **repository-level only**. `RepositoryAccess` rows are written by `sync_user_repositories` from `GET /user/installations/{id}/repositories` (repos visible to both the user and the app). Missing and unauthorized both return 404. `require_owner=True` = GitHub admin permission on that repo.
- **Platform admins *(Phase 1)*:** numeric GitHub IDs in `ADMIN_GITHUB_IDS`; `require_admin` (deps.py) guards every `/api/v1/admin/*` route (404 for others); `is_admin` is returned by `/auth/me` for UI only. Demo user (negative id) is never admin. No database flag.
- Production guards in `Settings`: secret length, ENCRYPTION_KEY, webhook secret, secure cookies, Postgres, no mock LLM, no memory vector backend.

## 8. GitHub integration (READ)
OAuth App identity for sign-in; GitHub App installation tokens (JWT via PyJWT) for repo access, diff fetch, posting. Required App permissions: Pull requests R/W, Contents R, Metadata R. Comments are posted as the App bot. GitHub client: validated repo names, paginated reads, POSTs never auto-retried. No DELETE of comments implemented. `ReviewComment.github_comment_id` is stored on publish.

## 8a. Rate limiting, headers, monitoring, retention *(Phase 1; details in `docs/PHASE1_OPERATIONS.md`)*
- Limits: per-IP global (all routes except health and the GitHub webhook), per-user global (authenticated routes, reuses the cached session lookup), plus the existing route-specific IP limits. Backend = Redis when `REDIS_URL` is set; failure mode `memory|closed|open`, circuit breaker 15 s; client IP from `TRUSTED_PROXY_HOPS`.
- API security headers via `core/security_headers.py` (CSP `default-src 'none'`, nosniff, DENY, no-referrer, Permissions-Policy, HSTS in production). SPA headers + **Report-Only** CSP in `frontend/vercel.json` / `frontend/nginx.conf`.
- Sentry in API (`create_app`), worker (`runner.main`) and browser (`main.jsx`), all scrubbed; job failures, 5xx upstream errors and DB-connectivity failures are captured.
- Cleanup: `services/retention.py`, scheduled in the worker every `CLEANUP_INTERVAL_MINUTES` (advisory lock on PostgreSQL) or via `python -m app.scripts.cleanup`. Admin screen: `/app/admin/jobs`.

## 9. Queue and workers (READ)
`job_queue.py`: `enqueue` (dedup via savepoint), `enqueue_or_requeue`, `claim_next` (SKIP LOCKED on Postgres + fenced UPDATE), fenced `complete`/`fail`, exponential backoff + jitter, `recover_stale` (lease timeout), `cancel` (queued only; exists but is not exposed through any API), `requeue` (failed/cancelled; used by review retry). Job kinds: `review`, `publish`, `index`, `index_delete`. Worker: thread pool (`WORKER_CONCURRENCY`), heartbeat file health check, graceful shutdown. Timeouts are lease-based (a hung thread cannot be killed). There is **no scheduler / periodic job mechanism** (only the `recover_stale` loop inside the worker).

## 10. OpenAI / Pinecone (READ)
- OpenAI: chat model for review (`temperature 0`, structured output), embeddings for indexing and search; timeouts configured; provider errors mapped to retriable/permanent. Diff text, PR metadata, custom rules and retrieved context are wrapped as untrusted data; secrets redacted before sending; sensitive files excluded. **Code content leaves the system to OpenAI** (diff batches, index chunks, search queries).
- Pinecone: one namespace per repository (`repo-<id>`); vector id `<sha1(path)[:16]>#<chunk>`; metadata `repo_id, repository, branch, commit, path, language, start_line, end_line, text(≤1500 chars)`. **Raw code text is stored in Pinecone metadata.** Dimension check against the index; batched upsert (100); prefix `list` for per-file cleanup (serverless).
- Vector IDs do not include the branch, and the namespace does not either, so indexing more than one branch per repo would collide today.

## 11. Frontend (READ; UI never rendered in a browser by me)
Routes under `/app/*`: dashboard, repositories, pull-requests (+detail), reviews (+detail), code-search, rules, settings, settings/integrations; `/login`, `/auth/callback`. Design system: Tailwind CSS-variable tokens, light/dark, own UI kit (`components/ui`), Geist Pixel font self-hosted (`/fonts`, fetched by `npm run fonts:install`). Search page filters: repository + language only; copy says it searches the default branch. `index.html` contains one **inline script** (theme bootstrap) → relevant to CSP. Favicon: `<link rel="icon" type="image/svg+xml" href="/logo.svg">` only; `logo.svg` is a 39 KB traced-path "S" mark; `public/brand/synaxys-logo.svg` is also present.

## 12. Environment variables
See `.env.example` (77 settings after Phase 1 added redis/rate-limit, admin, sentry and retention groups, documented there and cross-checked by `tools/check_docs.py`). Groups: core, GitHub OAuth/App/webhook, OpenAI, Pinecone, `ENCRYPTION_KEY`, sessions/cookies/proxy, review limits, index limits, worker. Frontend uses no secrets.

## 13. Deployment (READ; never applied)
Vercel (`frontend/vercel.json`: rewrites `/api/*` to a hard-coded `https://synaxys-api.onrender.com`, SPA fallback, 3 security headers) + Render (`render.yaml`: API runs `alembic upgrade head` then uvicorn; separate worker; Postgres). Docker Compose: postgres + api + worker + nginx web. `frontend/nginx.conf` sets the same 3 headers.

## 14. Existing security measures (READ)
Webhook HMAC before parsing; request size cap; CSRF + Origin check; hashed session tokens; Fernet token encryption with rotation script; secret redaction in logs, prompts, findings and index chunks; prompt-injection layering (untrusted wrapping, evidence/line validation, no tools); production config guards; `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` (API, nginx, Vercel); non-root Docker images; `pip-audit` and `npm audit` in CI.

## 15. Limitations / technical debt
**Resolved in Phase 1 (code written; see §17 for what was actually run):** distributed rate limiting (old #1), CSP/HSTS/Permissions-Policy (#2), error tracking (#3), no cleanup (#4), no admin role/UI (#5), SAST/secret/dependency automation (#13: Semgrep, Gitleaks, Dependabot added; they have not run yet), the `.gitignore`/ZIP hygiene problem (#16, new safe-archive tool).
**Still open:**
1. IP limits depend on `TRUSTED_PROXY_HOPS` matching the real proxy chain (Vercel -> Render): unverified; the per-user limit does not depend on it.
2. The CSP is Report-Only until verified in a browser on the real deployment.
3. ~~cancel~~, ~~dismissal~~, ~~comment deletion~~: implemented in Phase 2 (code written; DB/UI tests NOT RUN).
6. ~~Indexing limits~~ resolved in Phase 3 (code written; DB tests NOT RUN). Remaining indexing gaps: identical files are embedded once per branch; only the root `.gitignore`; no UI for per-repository globs; a one-time full re-embedding when upgrading existing indexes.
7. Search PR links exist (Phase 2) and the branch selector exists (Phase 3); a hit only has a related PR when a stored PR's head commit/branch matches. The GitHub review *summary* body cannot be deleted by this feature. Dismissal carry-over treats a finding as new if its evidence text changed.
8. ~~No workspace/notification concept~~ resolved in Phase 4 (DB/UI tests NOT RUN). Still open: no e-mail/Slack delivery, repositories cannot move between workspaces, comment/finding-level audit events are not attributed to a workspace.
9. ~~No account deletion/export~~ resolved in Phase 4 (remote GitHub token revocation untested).
10. Python dependencies have no lockfile; pins and the new Phase 1 ranges (`redis`, `sentry-sdk`, `@sentry/react` 8.47.0) are unverified. `package-lock.json` must be regenerated (`npm install`) after the `@sentry/react` addition or `npm ci` fails.
11. The e2e mock API is hand-maintained and can drift.
12. Real deployment uses `backend/start.py` (API and worker in one Render web service); `render.yaml` describes a two-service layout. Free instances sleep, which also pauses the in-worker cleanup (use the external command).
13. Retention of webhook deliveries (>= 7 days) is the replay-recognition window; older replays are possible but are neutralised by the unique review dedup keys.
14. A development SQLite database containing a real user (encrypted token + session hashes) was found in the uploaded ZIP; see `docs/KEY_ROTATION.md`. It is not in any Docker image (the backend Dockerfile copies only `app/` and `migrations/`).

## 16. Key file dependencies
`api/deps.py` ← every router. `repositories/access.py` ← all PR/review/search/index routes. `services/job_queue.py` ← webhook_service, github.py, pull_requests.py, repositories.py, workers. `services/review_service.py` → `agents/*`, `finding_validation`, `comment_service`. `services/indexing_service.py` → `index_policy`, `chunking`, `vector_service`, `embedding_service`. `models/entities.py` ← everything; any schema change needs a **new explicit Alembic migration** (do not edit 0001).

## 17. Testing (instructions)
```
cd backend && python tools/run_pure_tests.py        # stdlib only
cd backend && pip install -r requirements-dev.txt && pytest -q && ruff check .
cd frontend && npm ci && npm run lint && npm test && npm run build && npm run e2e
```
**Executed (RAN):** `python backend/tools/run_pure_tests.py` -> **114 passed, 0 failed** (99 original + 15 Phase 1); `check_docs.py`, `check_repo.py`, `check_names.py`, `check_imports.py` PASS; `gen_api_docs.py` (43 endpoints); `compileall`; frontend scrub logic via Node; `make_source_zip.py`.
**Phase 5 (batch 17):** pure tests now 151/151 (12 new in `test_phase17_pure.py`); `Legal.test.jsx` NOT RUN.
**Phase 4 (batch 16):** pure tests now 139/139 (10 new in `test_phase16_pure.py`); `test_phase16_db.py` and `Workspaces.test.jsx` NOT RUN; `test_foundation.py` table count adjusted (25).
**Phase 3 (batch 15):** pure tests now 129/129 (10 new in `test_phase15_pure.py`); `test_phase15_db.py` and `BranchIndexPanel.test.jsx` NOT RUN; `test_phase9_db.py` and `test_foundation.py` were adjusted on purpose.
**Phase 2 (batch 14):** pure tests 119/119 at that point (5 new in `test_phase14_pure.py`); `test_phase14_db.py` and `ReviewWorkflow.test.jsx` NOT RUN.
**NOT RUN (all phases):** pytest (incl. `test_phase13_db.py`, `test_phase13_redis.py`, `test_phase14_db.py`), ruff, alembic (incl. 0003), Vitest (incl. `monitoring.test.js`), eslint, vite build, Playwright, Docker, workflow/compose/render YAML validation, real Redis/Sentry/GitHub/OpenAI/Pinecone/PostgreSQL, browser CSP.

## 18. Change log
| Date | Change |
|---|---|
| 2026-11-19 | Initial audit; no code changed. Roadmap in `IMPLEMENTATION_ROADMAP.md`. |
| 2026-11-20 | Phase 1 (batch 13): Redis rate limiting, Sentry, headers + Report-Only CSP, admin job screen, retention cleanup + migration 0003, Semgrep/Gitleaks/Dependabot, safe ZIP tool, key-rotation runbook, github sync 409 on undecryptable token. |
| 2026-11-20 | Phase 2 (batch 14): finding dismissal (+carry-over), queued-review cancel, GitHub comment delete, search PR links; migration 0004; 4 endpoints; UI. |
| 2026-11-20 | Phase 3 (batch 15): branch-aware batched incremental indexing, large-repo (truncated tree) support, .gitignore + per-repo globs, embedding budget, branch selector in search, branches panel; migration 0005; 4 endpoints + 1. |
| 2026-11-20 | Phase 4 (batch 16): workspaces + RBAC + invitations (derived repository access), notifications, account export/deletion, retention additions; migration 0006; 24 endpoints; UI. |
| 2026-11-20 | Phase 5 (batch 17): favicon set, proprietary LICENSE notice, vulnerability-reporting policy, Privacy Policy and Terms drafts (public `/legal/*` pages, footer links), placeholder checklist; workspace deletion now purges repository data. |
