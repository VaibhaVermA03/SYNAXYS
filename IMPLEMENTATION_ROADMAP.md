# SYNAXYS — Audit Findings and Implementation Roadmap

Based on a direct read of the uploaded ZIP (see `PROJECT_CONTEXT.md`).

## Status (updated 2026-11-20) — all five phases are written; what remains is YOUR local test run, configuration, placeholders and legal review
| Phase | State |
|---|---|
| 1 Core security and reliability | **Written and delivered (batch 13)**; only the stdlib-testable parts executed (114/114 pure tests, repo checks). Needs your local `pytest`/build/CI run and the configuration in `docs/PHASE1_OPERATIONS.md` |
| 2 GitHub review workflow | **Written and delivered (batch 14)**: dismissal, cancel, comment delete, search PR links (branch selector deferred to after Phase 3, as agreed). Pure tests 119/119; DB/UI tests NOT RUN |
| 3 Indexing (+ branch selector after it) | **Written and delivered (batch 15)**: branch-aware, batched, incremental, large-repo capable; search branch selector. Pure tests 129/129; DB/UI tests NOT RUN |
| 4 Workspaces, notifications, account | **Written and delivered (batch 16)**: workspaces/RBAC/invitations, notifications, account export + deletion. Pure tests 139/139; DB/UI tests NOT RUN |
| 5 Trust and compliance | **Written and delivered (batch 17)**: favicon, proprietary licence notice, security policy, Privacy Policy + Terms drafts (placeholders; need your details and legal review). Pure tests 151/151; UI tests NOT RUN |

**Owner decisions (2026-11-20):** D1 independent SYNAXYS workspaces with their own invitations/members/roles, designed so a workspace can hold several GitHub installations; D2 admins = `ADMIN_GITHUB_IDS` allow-list (backend-enforced); D3 Redis rate limiting; D4 proprietary licence with placeholders; D5 Sentry. Order confirmed, with branch selector after Phase 3.
Sections A-E below are the original audit text; where Phase 1 resolved an item, `PROJECT_CONTEXT.md` section 15 is authoritative.

## A. Where the codebase differs from the task list
| Task | What the code actually shows | Consequence |
|---|---|---|
| 6 Workspaces | No workspace/org/membership concept. Access = `repository_access` rows synced from GitHub | Needs a design decision (below); touches almost every query |
| 3 Cancel | `job_queue.cancel()` already exists (queued-only, atomic UPDATE) but no API/UI calls it | Mostly wiring + review/job state sync + audit; smaller than expected |
| 4 Delete comments | `review_comments.github_comment_id` is stored on publish; no GitHub DELETE method | Feasible; must verify the id is a *review comment* id (REST `pulls/comments/{id}`) |
| 2 Dismiss | `review_findings.status` has `dismissed`, set only by cancelling the comment; dedup is per review | Reappearing findings is a real bug: new review = new rows |
| 1 Branch selector | Only the default branch is ever indexed; vector IDs and namespaces have no branch | Branch selector is meaningless until multi-branch indexing exists, so Task 5 must come first for this part |
| 1 PR link | Search hits come from indexed branch commits, not PRs. `PullRequest.html_url` exists | "Related PR" must be derived (head branch / commit match); some hits will have none. Don't fabricate |
| 13 Rate limit | In-process limiter keyed by IP only; no user key | Redis or Postgres-backed limiter needed once >1 API instance |
| 15 Favicon | `index.html` already links `/logo.svg` (traced "S" mark) | Partly exists; missing PNG/ICO/apple-touch/manifest, not "no favicon" |
| 16 SECURITY.md | `SECURITY.md` exists but is an internal threat model, not a disclosure policy | Add a disclosure section; keep existing content |
| 10 Scanning | CI already runs `pip-audit` and `npm audit` | Add Semgrep + secret scan + Dependabot only; no duplicate dependency scanner |
| 9 Admin screen | There is no admin role | Must define who an admin is first |

## B. Production-risk findings (prioritised)
**High**
1. `backend/synaxys_dev.sqlite3` in the ZIP contains a real user row with an encrypted GitHub token and 12 session rows. Confirm it was never committed or shared; if in doubt, revoke the GitHub authorization and rotate `ENCRYPTION_KEY`/`APP_SECRET_KEY`. (counts only inspected)
2. Rate-limit bypass: per-process state, and with `TRUST_PROXY_HEADERS=true` the first `X-Forwarded-For` value is trusted; behind Render/Vercel that value can be client-supplied unless the platform overwrites it. Needs verification against your real proxy chain.
3. Raw code text (≤1500 chars/chunk) is stored in Pinecone metadata and sent to OpenAI. Legitimate for the feature, but must be disclosed (Task 16) and should be a conscious retention decision.
4. Unbounded table growth (sessions, webhook deliveries, jobs, audit logs, indexing jobs).

**Medium**
5. No CSP/HSTS/Permissions-Policy; inline theme script requires a hash or external file.
6. No error tracking; failures are visible only in logs/DB.
7. Indexing refuses truncated trees; `INDEX_MAX_FILES` cut is alphabetical, so large repos are silently partially indexed in an arbitrary way.
8. No cost controls on OpenAI/Pinecone beyond per-file limits.
9. Python deps lack a lockfile; several pinned versions unverified (no network here). First real `pip install` may fail.
10. Audit `meta` and per-user-only audit trail will not satisfy workspace audit requirements.

**Low / hygiene**
11. Committed/shipped artefacts: `.ruff_cache`, `playwright-report`, `test-results`.
12. Migration 0001 uses `create_all` from live metadata; a clean DB gets *future* columns from 0001. Fine for now, wrong long-term. New migrations must be written defensively.
13. 67 backend tests, ruff, alembic, frontend tests/build, Docker and CI have never been run. Baseline is unknown until you run them locally; I ran only the 99 stdlib tests (all pass).

## C. Proposed phases (user's order, with two dependency adjustments)
**Adjustment 1:** Task 5 (multi-branch/partial indexing) moves before the *branch selector* part of Task 1. PR navigation in Task 1 can ship in Phase 2; the branch selector ships after Phase 3.
**Adjustment 2:** Task 6 (workspaces) is a tenancy change. Notifications (7) and Export/Delete (8) depend on it, so it stays first in Phase 4, and I would add the workspace column to *new* tables from Phase 1 onward only where I know the model (see decision D1).

### Phase 1 — Reliability and security (Tasks 13, 14, 11, 9, 12, 10)
Order: 13 → 11 → 12 → 9 → 14 → 10.
| Task | Plan | Files (expected) | Migration |
|---|---|---|---|
| 13 | `core/rate_limit.py` gets a pluggable backend: Redis (atomic Lua/INCR window) with an explicit failure policy (fail-closed on auth endpoints, fail-open with logging elsewhere); key = route + user id + IP; per-route table in config | `core/rate_limit.py`, `api/deps.py`, `core/config.py`, `.env.example`, `render.yaml`, `docker-compose.yml`, `requirements.txt`, tests | none |
| 11 | Sentry SDK in API + worker + frontend; `before_send` scrubbing; release/env tags; job-failure capture in `workers/runner.py`; structured logs get request/job ids | `main.py`, `workers/runner.py`, `core/logging.py`, `frontend/src/main.jsx`, `vite.config.js`, ErrorBoundary | none |
| 12 | Periodic maintenance loop in the existing worker (leader-elected via DB advisory lock on Postgres), batched deletes, config for retention, dry-run mode | new `services/retention.py`, `workers/runner.py`, `core/config.py` | indexes on `received_at`, `created_at`, `expires_at`, `finished_at` |
| 9 | `/api/v1/admin/jobs` list/detail/retry/stats with pagination and filters; sanitized errors only; retry via existing fenced `requeue`; admin UI page | new `api/v1/admin.py`, `schemas/admin.py`, frontend `features/admin/*` | depends on D2 |
| 14 | Report-only CSP first (Vercel `headers`, nginx, API); externalise or hash the inline script; HSTS, Permissions-Policy | `frontend/vercel.json`, `nginx.conf`, `index.html`, `main.py` | none |
| 10 | Semgrep workflow (pinned action, no secrets exposed to PR code), gitleaks, `dependabot.yml`; keep `pip-audit`/`npm audit`; severity thresholds | `.github/workflows/security.yml`, `.github/dependabot.yml`, `SECURITY.md` | none |

### Phase 2 — Review workflow (Tasks 1a, 2, 3, 4)
- **2** Add `dismissed_by_id`, `dismissed_at`, `dismiss_reason` to `review_findings`; new `POST /reviews/{id}/findings/{fid}/dismiss|restore`; carry dismissal across reviews by a PR-scoped fingerprint check in `review_service` so dismissed findings do not return as open. Comment state and finding status stay separate.
- **3** `POST /reviews/{id}/cancel`: in one transaction cancel the `background_jobs` row via the existing fenced `cancel()` (queued only) and set `code_reviews.status=cancelled` only if that UPDATE affected one row; add `cancelled_by_id/at`; worker already skips non-queued jobs. Race tests with SQLite and, if you can, Postgres.
- **4** `DELETE /reviews/{id}/comments/{cid}/github`: admin-only; verify comment id belongs to the repo/PR by fetching it first; call GitHub DELETE; treat 404 as already-deleted; new `ReviewComment` state `deleted` + `deleted_at/by`; audit entry; never delete the row.
- **1a** Search hit gets `pull_request` (derived, nullable) and an "Open on GitHub" link built from stored `html_url` only.

### Phase 3 — Indexing (Task 5, then Task 1b)
Design (to be confirmed before coding): replace the single-shot run with a batch model: `indexing_batches` table (job, batch no., status, attempts, error, file range), planner that splits the plan into batches of N files, one queue job per batch with retries, `.gitignore` + extended default exclusions + extension allow/deny list per repo, per-job and per-day embedding budget, tree-truncation fallback using per-directory tree requests instead of refusal, branch included in namespace or vector ID, per-branch `indexed_files`. Pinecone cost note: vectors per branch multiply storage, so default stays "default branch + opt-in branches".
Migrations: `indexing_batches`, `indexed_files.branch`, repository index settings columns.

### Phase 4 — Collaboration and account (Tasks 6, 7, 8)
Depends on D1. Introduces `workspaces`, `workspace_members`, `workspace_invitations`, `notifications`, `data_exports`; `workspace_id` on repositories (or installations) and all derived queries; an authorization layer in `repositories/access.py` replaced by workspace-aware checks; Pinecone namespace gets workspace prefix. Polling (not websockets) for notifications. Export: JSON in a ZIP, authenticated download endpoint, expiry through the Phase 1 cleanup job. Deletion: re-auth via fresh GitHub OAuth round-trip, ownership transfer or workspace deletion, token revocation, vector cleanup via existing `index_delete` jobs.

### Phase 5 — Trust and compliance (Tasks 15, 16)
Favicon set generated from the existing mark (SVG + PNG sizes + ICO + apple-touch + manifest), `SECURITY.md` disclosure section, Privacy/Terms as draft pages with `[PLACEHOLDER]` markers, footer links. LICENSE only after you answer D4.

## D. Decisions I need from you (nothing else blocks Phase 1)
- **D1 Workspace model (blocks Phase 4 only):** (a) workspace = a GitHub installation/org, members auto-derived from GitHub access; (b) independent SYNAXYS workspaces with their own invitations that own installations/repos; (c) hybrid. I recommend (b), because the task asks for invitations, roles and ownership transfer independent of GitHub.
- **D2 Admin definition (blocks Task 9):** env allow-list of GitHub user IDs (no migration, simplest) or an `is_admin` column. I recommend the env allow-list.
- **D3 Rate-limit store (blocks Task 13):** Redis (Render Key Value / Upstash; extra service and cost) vs a Postgres-backed counter (no new infrastructure, slower, adds write load). I recommend Redis if you plan more than one API instance; tell me if you will run one.
- **D4 LICENSE (blocks that sub-item):** is this proprietary/closed-source, and who is the copyright holder?
- **D5 Monitoring provider:** Sentry (my default) or something else; you create the project and DSNs.
- Also useful, not blocking: confirm the Render plan and whether the worker runs as a separate paid service (the retention job design assumes it does).

## E. Delivery and verification rules I will follow
- Individual complete files only, exact paths, no project ZIP (the safe archive tool `backend/tools/make_source_zip.py` is for *your* uploads to me); PROJECT_CONTEXT.md updated each phase; migrations are new Alembic files only.
- Every check reported as PASS / FAIL / NOT RUN with evidence. In this chat I can run: the stdlib test runner, Python compile/AST checks, YAML/JSON parsing, JS syntax checks if Node is present, and unit logic for new pure modules. I cannot run FastAPI/SQLAlchemy tests, Vite/Vitest, Docker, Redis, Sentry, or any GitHub/OpenAI/Pinecone call without installing packages, so those will be labelled NOT RUN until you run them locally.
- Regression baseline: please run `pytest -q`, `ruff check .`, `npm ci && npm test && npm run build` once and send me any failures, since the 67 DB/API tests have never been executed anywhere.
