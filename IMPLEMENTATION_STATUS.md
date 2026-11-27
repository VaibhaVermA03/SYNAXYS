# SYNAXYS Implementation Status

## Batch 1 (Phase 1 + part of Phase 2) — COMPLETE
- Directory scaffold per spec (frontend/, backend/), brand placeholder dir, .gitignore
- backend/requirements.txt + requirements-dev.txt (pinned; NOT verified by install — no network in build sandbox)
- backend/app/core/security.py: HMAC-SHA256 webhook verification (constant-time), secret detection/redaction, stable finding fingerprints
- backend/app/services/diff_service.py: unified-diff parser, single-hunk line-range validation (never relocates findings), binary detection
- backend/app/agents/review_policies.py: system policy, prompt-injection markers, untrusted-content wrapping
- backend/app/tests/test_core_pure.py: 8 tests

## Checks
| Check | Result |
|---|---|
| Pure-Python unit tests (8) via stdlib runner | PASS |
| pytest (`cd backend && pytest`) | NOT RUN (pytest not installed, no network) |
| ruff, alembic, frontend build/tests, Docker, audits | NOT RUN |

## Decisions
- Job queue: DB-backed (`background_jobs`, SKIP LOCKED), no Redis.
- Sessions: server-side, HttpOnly cookie. GitHub App for repo access, OAuth for sign-in.
- Token encryption: Fernet (cryptography), key from ENCRYPTION_KEY env.

## Batch 2 (rest of Phase 2) — COMPLETE
- core/config.py (pydantic-settings, production guards), exceptions.py (error envelope + handlers), logging.py (JSON + redaction), encryption.py (Fernet/MultiFernet rotation)
- db/base.py, db/session.py (SQLite FK pragma), db/seed.py (demo data, all is_demo=True)
- models/entities.py: 17 entities (users, oauth_identities w/ encrypted token, sessions as token hashes, installations, repositories, repository_access, review_configurations, review_rules, pull_requests, webhook_deliveries (unique delivery_id), background_jobs (dedup_key, run_after index), code_reviews (unique dedup_key), findings (unique review+fingerprint), comments, posting_attempts, indexing_jobs, audit_logs)
- Alembic: alembic.ini, migrations/env.py, baseline 0001 (create_all from metadata; later changes must be explicit migrations)
- .env.example, backend/pytest.ini

## Batch 4 (Phase 4: webhooks, durable queue, worker) — COMPLETE (source), partially verified
- services/webhook_events.py: strict payload validation (types, lengths, SHA format; errors never echo payload) + routing decisions (pull_request opened/synchronize/reopened/closed, push default-branch only, installation, installation_repositories)
- services/webhook_service.py: idempotency via unique delivery_id; a previously FAILED delivery GUID is reprocessed on GitHub redelivery, completed ones are duplicates; PR upsert; reviews enqueued only for enabled repos + allowed actions; older queued reviews for superseded commits cancelled; installation deleted/suspend/repo removal disables repos and queues index_delete; enqueue-only (no LLM in request path)
- api/v1/webhooks.py: raw-body HMAC-SHA256 (constant-time) BEFORE JSON parsing; 401 bad/missing signature, 400 bad headers/JSON/payload, 413 oversize, 503 if secret unset, 200 duplicate/ignored/updated, 202 queued, ping->pong
- services/job_queue.py: enqueue (dedup via savepoint), claim_next (SKIP LOCKED on PostgreSQL + fenced UPDATE), fenced complete/fail, exponential backoff w/ jitter, max attempts, stale-lock recovery, cancel, requeue
- services/job_policy.py: backoff, staleness, error sanitization/redaction, retriable-vs-permanent classification
- workers/runner.py: bounded thread pool, lease-based timeouts, graceful shutdown (SIGTERM/SIGINT), heartbeat file + `--healthcheck`, final failure marks CodeReview failed (no endless "processing"); workers/registry.py: kinds without a handler FAIL loudly ("No handler for job kind") — review/index handlers arrive in Phases 7/9
- config.py: +job_default_timeout_seconds, worker_poll_interval_seconds, worker_heartbeat_path, worker_shutdown_grace_seconds
- Run worker: `cd backend && python -m app.workers.runner`

## Batch 5 (Phase 5: frontend foundation, auth screen, layout, dashboard, repositories) — COMPLETE (source), partially verified
Backend additions: POST /auth/demo-login (seeded sample user; 404 in production or when DEMO_LOGIN_ENABLED=false), GET /dashboard (aggregates scoped through RepositoryAccess; demo data flagged), `demo_login` in /auth/config.
Frontend (React 18 + Vite 5 + Tailwind 3.4 + React Router 6 + TanStack Query 5 + Lucide; JS/JSX):
- Config: package.json (exact pins), vite.config.js (dev proxy /api -> backend so cookies are same-origin), tailwind (CSS-variable tokens, light/dark), eslint flat config, vitest+jsdom setup
- lib/api.js: fetch client (credentials, in-memory CSRF token on unsafe methods, error envelope -> ApiError, network error, 401 event); services/index.js
- app/AuthProvider (session via /auth/me, 401 handling, logout), ThemeProvider (preference only in localStorage), ToastProvider
- components: ui (Button, Card, Input, Badge, Skeleton, EmptyState, ErrorState, Pagination, ConfirmDialog, SeverityBadge, StatusBadge), layout (Logo w/ text fallback for /brand/synaxys-logo.svg, responsive Sidebar drawer, Topbar w/ theme toggle + workspace + sign-out)
- Pages: LoginPage (GitHub button, explicit not-configured screen, callback error messages, labelled demo sign-in), AuthCallbackPage, DashboardPage (empty state, severity bars, status, recent activity, demo banner, quick actions), RepositoriesPage (search/filter/pagination, sync, connect/disconnect with confirm, admin-only controls, index status/errors, install link)
- Routes for all spec'd URLs exist; unbuilt features render an explicit "not built in this checkpoint" notice (NotBuiltYet) — Phase 6/9/10 replace these
- Tests written: api client, ProtectedRoute, LoginPage, RepositoriesPage (frontend); demo-login + dashboard isolation (backend)

## Batch 6 (Phase 6: PR feed, diff viewer, findings, reviews, review rules) — COMPLETE (source), partially verified
Backend:
- services/diff_service.py: build_file_diff (added/removed/renamed/modified; missing/truncated patch -> skipped_reason; binary; oversized), count_patch_changes
- services/github_service.py: list_pull_request_files (validated repo name, paginated); services/rule_validation.py (name/instruction/patterns/languages; rejects prompt-override text, delimiter spoofing, control chars, path-traversal globs)
- repositories/access.py: get_pr_for_user, get_review_for_user (404 on no access)
- API: GET /pull-requests (search, repo, state open/closed/merged, review status, sort/order, pagination, latest-review summary + severity counts), GET /pull-requests/{id} (detail + review history + can_request_review), GET /pull-requests/{id}/diff (demo fixtures served locally and labelled; real PRs via GitHub App installation token, clear 503 if app not configured; max_files/max_patch_bytes limits with omitted_files), POST /pull-requests/{id}/review (rate-limited; refuses demo/unconnected/closed; reuses in-flight review), GET /reviews, GET /reviews/{id} (findings w/ evidence, confidence label, comment draft state, category breakdown, policy flags), POST /reviews/{id}/retry (failed/cancelled only; never leaves a queued review without a job), GET/POST/PATCH/DELETE /review-rules (author-only edit, repo-scoped rules need GitHub admin, 422 with per-field errors)
- exceptions.py: ValidationFailed (422) + field errors in envelope
Frontend: lib/diff.js (split-row pairing, inline finding mapping, file tree); components FindingCard (AI-suggestion label, confidence, evidence, summary-only note, comment state), ReviewParts (SeverityCounts, ReviewProgress, CategoryBreakdown, FindingGroups), FileTree, DiffViewer (unified/split, line numbers, inline findings, skipped-file explanations); pages PullRequestsPage, PullRequestDetailPage, ReviewsPage, ReviewDetailPage, RulesPage + RuleDialog (react-hook-form + zod, server field errors); polling while reviews are queued/processing
Deliberately NOT shown (no fake controls): approve/publish/edit-comment buttons (Phase 8), "test rule" (needs the Phase 7 engine), cross-file context panel (needs Phase 7/9 retrieval)

## Batch 7 (Phase 7: AI review engine) — COMPLETE (source), partially verified
- services/review_context.py: eligibility (skips binary, deleted, lockfiles/generated, vendored/build, and SENSITIVE files like .env/*.pem — never sent to the model), glob matching (`**`, `*`, `?`, `{a,b}`), rule selection by language/pattern, size-bounded batching with total/batch limits, line-numbered diff rendering with secret redaction
- agents/prompts.py: system policy + task; ALL repo-derived text, PR metadata, custom rules and retrieved context are wrapped as untrusted DATA (delimiter spoofing neutralised)
- services/finding_validation.py: closed enums (+aliases), bounded/redacted/control-stripped text, file must be in reviewed diff, evidence quote must literally occur in that file's (redacted) diff, line range kept ONLY if valid within one hunk (else cleared — never relocated), confidence threshold, fingerprint + similar-title dedup, severity ordering, cap, honest summary with discard counts
- agents/review_graph.py: bounded deterministic pipeline (no agent loops), deadline checks, max batches; agents/llm.py: OpenAIReviewLLM (LangChain ChatOpenAI + structured output, temperature 0), provider-error mapping (retriable vs permanent, no leaked detail), KeywordMockLLM (explicit opt-in REVIEW_USE_MOCK_LLM, labelled "not AI"), get_review_llm (NEVER silently fakes); agents/review_schemas.py (pydantic schema)
- services/review_service.py: executes a review, cancels superseded/disconnected, persists findings + DRAFT comments only for verified inline locations, failure -> back to 'queued' with sanitized note + re-raise; workers/review_worker.handle_review wired into registry; runner marks review failed after final attempt
- services/comment_service.py: draft comment text (AI disclaimer footer always preserved)
- POST /review-rules/test (rate-limited; snippet run through the real engine, nothing stored); UI "Test this rule" panel (mock output labelled; 503 shown as clear config message)
- Nothing is posted to GitHub in this phase.

## Batch 8 (Phase 8: approval, authorized publishing, audit trail) — COMPLETE (source), partially verified
- services/publish_logic.py (pure): fingerprint markers `<!-- synaxys:fp=... -->`, RIGHT-side inline payloads (multi-line aware), duplicate planning, publish preconditions (demo / not completed / repo disconnected / PR closed / STALE head / app not configured), comment state transitions; event is hard-coded "COMMENT" (never APPROVE/REQUEST_CHANGES)
- services/publish_service.py: approve (admin only; drafts->approved, records approver), edit (re-approval required; empty/secret-containing text rejected; published comments locked), publish: atomic per-comment 'publishing' lock (stale lock TTL 5 min), re-lists GitHub comments and skips anything whose fingerprint marker already exists (survives crashes/retries), one comment-only review incl. summary, on 422 falls back to per-comment posting to isolate bad locations (marked 'failed'), transient errors release comments back to 'approved', each outcome committed immediately, every attempt recorded in review_posting_attempts + audit logs, 401/403/404 -> actionable "GitHub App needs Pull requests: Read & write" error
- services/github_service.py: write methods (POSTs never auto-retried: a 5xx may have been applied); `valid_repo_name` now rejects '.'/'..' segments (path-traversal bug found by tests, also fixed for list_pull_request_files)
- API (repo ADMIN only, CSRF enforced): PATCH /reviews/{id}/comments/{cid} (body and/or state draft|cancelled), POST /reviews/{id}/approve, POST /reviews/{id}/publish (rate-limited), GET /reviews/{id}/posting-attempts; review detail adds can_manage/approved_comments/publishable/publish_blocker; GET/PATCH /github/repositories/{id}/config (admin-only; auto_publish forces require_approval=false and vice versa; audited)
- Auto-publish: only when a repo admin enabled it; review completion enqueues a 'publish' job, worker re-checks the policy at execution time, approves drafts as the system and publishes (attempts show actor "auto-publish"); workers/publish_worker.py registered
- Frontend: CommentActions (edit/approve/unapprove/dismiss/restore, shows exact proposed text), ReviewDetailPage action bar (approve all, publish N with confirmation dialog explaining visibility, stale/demo/permission blockers explained, publishing history); no controls for non-admins or demo; repoConfigService added (settings UI comes in Phase 10)

## Batch 9 (Phase 9: Pinecone indexing, tenant-isolated search, review context) — COMPLETE (source), partially verified
Backend:
- services/chunking.py (deterministic line-aware chunks, definition-boundary heuristics per language, real line numbers, minified-line splitting), services/index_policy.py (exclusions: binary/sensitive/generated/vendored/oversized; vector IDs `<sha1(path)[:16]>#<n>`; namespace `repo-<id>`; incremental planning by git blob SHA incl. purge of newly-excluded files; FULL-FILE secret detection incl. multi-line keys and secrets split across chunk fragments -> affected chunks never embedded)
- services/embedding_service.py (OpenAIEmbedder via langchain-openai with `dimensions`, HashEmbedder lexical dev adapter, dimension-mismatch hard error), services/vector_service.py (PineconeStore: describe_index dimension check, batched upsert, prefix list/delete for serverless, namespace delete; InMemoryStore explicit dev/test adapter; error mapping; `indexing_available` / `get_vector_store` / `get_embedder` never fake when unconfigured)
- GitHub client: get_branch_head, get_tree (recursive), get_blob (size-capped), all inputs validated (branch/sha/repo) before URL building
- services/indexing_service.py: incremental run (plan -> delete removed -> fetch/chunk/embed/upsert changed -> delete stale chunks AFTER upsert), per-file progress committed (deadline/timeout/retry resumes), truncated-tree refusal, visible failure state ("Will retry: ..."), audit log; delete_repository_index (namespace drop + IndexedFile rows)
- workers/indexing_worker.py: handle_index (creates IndexingJob for webhook pushes), handle_index_delete (skips if repo was reconnected; no vector store needed if never indexed); registry already loads both
- API: POST /code-search/query (server-side scope = RepositoryAccess ∩ connected ∩ indexed, per-namespace queries, repo_id re-verified in metadata, filters repository/language/branch, deterministic relevance explanation, GitHub permalink, rate-limited, 503 with clear codes when Pinecone/OpenAI missing), POST /repositories/{id}/index (admin; refuses demo/unconnected/disabled/unconfigured; reuses running job), GET /repositories/{id}/index-status (availability + backend label + live job counts)
- Cross-file context for reviews: services/context_retrieval.py (own namespace only; excludes changed files; min score; caps) wired lazily via ReviewInput.context_fn; review summary ALWAYS states whether context was used/unavailable/failed; retrieved text is untrusted-wrapped
- Models/migrations: IndexedFile + migration 0002 (idempotent vs baseline create_all); config: vector_backend, index_*, context_*, search_rate_limit_per_minute
- Latent bug fixed: disconnect cleanup jobs used a permanent dedup_key, so a SECOND disconnect never queued cleanup -> job_queue.enqueue_or_requeue (used by disconnect + webhook installation/repo removal)
Frontend: CodeSearchPage (repo + language filters, snippet/path/lines/score/explanation/GitHub link, no-index empty state, demo-embedding note, config errors shown verbatim), RepositoriesPage indexing controls (Index code / Re-index / Retry indexing, admin only, live IndexProgress with real counts + aria progressbar, failures shown)

## Batch 10 (Phase 10: settings/integrations, usage metrics, error handling, e2e) — COMPLETE (source), partially verified
Backend:
- services/integration_status.py (pure; booleans + non-secret values only; mock/memory modes labelled) + GET /settings/integrations (status, webhook URL, OAuth callback URL, install URL, whether a GitHub token is stored) + GET /settings/audit (caller's OWN audit trail only)
- GET /dashboard adds reviews_by_day (14 days, zero-filled), published_comments, failed_reviews (all scoped to accessible repos)
Frontend:
- SettingsPage (account, theme, GitHub credential revocation behind confirmation, readable activity log), IntegrationsPage (status per integration with the env vars to set, copyable webhook/callback URLs, GitHub App permissions/events, demo-feature banner), ReviewPolicyPanel (admin repos only; manual approval vs auto-publish radio; enabling auto-publish needs explicit confirmation explaining the risk; allowed PR events; file/patch limits; indexing toggle; at-least-one-event guard)
- Dashboard: comments published, failed reviews, accessible 14-day bar chart, index summary
- Error handling: ErrorBoundary (no blank page on render crash), NotFoundPage (in-app and standalone), CSRF-failure recovery (api emits event; AuthProvider refreshes session state); the "not built in this checkpoint" placeholder page is gone — every route is implemented
- Playwright: playwright.config.js, e2e/mockApi.js (stateful fake API with CSRF check), e2e/review-flow.spec.js (auth -> connect + index repo -> PR diff -> mocked AI review -> inspect AI-labelled finding -> approve -> confirmation -> publish -> history -> code search; protected routes/sign-out; 404 + retryable error), e2e/demo-backend.spec.js (opt-in with E2E_BACKEND=1 against a seeded real backend). No real GitHub/OpenAI/Pinecone accounts are used.

## Batch 11 (Phase 11: documentation + deploy configs) — COMPLETE
Docs (all cross-checked mechanically, see below): README.md (status warning, demo vs credentialed feature table, macOS/Linux and Windows PowerShell quick starts, layout), SECURITY.md (assets/trust boundaries, threat table with residual risk, production guards, key generation + rotation, data sent to third parties, known limitations), DEPLOYMENT.md (Vercel rewrite + Render API/worker + Postgres + Pinecone, verification checklist, backups/recovery), TESTING.md (suite-by-suite honest status table), docs/ARCHITECTURE.md (Mermaid component + review-lifecycle diagrams, job kinds, authorization model, data model, decisions), docs/API.md + generated docs/API_ENDPOINTS.md (39 endpoints), docs/GITHUB_SETUP.md (identity vs installation vs permissions vs org policy, exact App settings, ngrok), docs/PINECONE_OPENAI.md, docs/TROUBLESHOOTING.md
Config/code changes made while documenting: complete `.env.example` (all 53 Settings, also copied to backend/.env.example), `DATABASE_URL` normalisation (postgres:// | postgresql:// -> psycopg), production guard now also rejects REVIEW_USE_MOCK_LLM and VECTOR_BACKEND=memory, `app/scripts/rotate_keys.py` (Fernet re-encryption), frontend/vercel.json, render.yaml (unverified)
Tools: backend/tools/check_docs.py (Settings <-> both .env.example files; npm scripts, python -m modules and backticked paths in docs exist), gen_api_docs.py (API table from route decorators — it caught that async routes were missing), run_pure_tests.py (stdlib-only runner)

## Batch 12 (Phase 12: Docker, CI, final inspection, final ZIP) — COMPLETE
- Docker: backend/Dockerfile (one image for API + worker, non-root, health check), frontend/Dockerfile (Vite build -> unprivileged nginx), frontend/nginx.conf (/api proxy + SPA fallback + headers), .dockerignore files, docker-compose.yml (postgres + api + worker + web; migrations on api start; worker waits for healthy api; DB not published)
- CI: .github/workflows/ci.yml (backend ruff/pytest/migrations/pip-audit, frontend lint/test/build/audit, Playwright, repo checks, docker build); backend/ruff.toml (E9+F)
- Final inspection tools: check_repo.py (secrets/forbidden files, 55 required files, frontend->backend route contract incl. the e2e mock), check_names.py (symtable undefined-name check), check_imports.py; all proven able to fail via planted-error negative controls
- TEST_REPORT.md generated from real command output; README/DEPLOYMENT/TESTING updated for Docker + CI

## FINAL STATE — what is and is not verified
Executed and PASS: 99 dependency-free tests; docs<->settings/scripts/paths; undefined-name scan (112 Python files); internal imports; JS import/export + unused-import scan; JS/JSX syntax (58 files); Python compile; YAML/JSON parse; API reference == 39 route decorators; markdown links; repo inspection (no secrets, 55 required files, 34 frontend calls within 39 backend routes).
NOT RUN: 67 backend API/DB tests, ruff, alembic 0001/0002, 13 Vitest files, eslint, vite build, Playwright (4 tests), pip-audit/npm audit, lockfiles (none generated), Docker/Compose build, CI run, all real GitHub/OpenAI/Pinecone/PostgreSQL behaviour, Render/Vercel deployment, any browser rendering/accessibility check.

## Decisions / caveats
- Repo listing uses GET /user/installations/{id}/repositories with the USER token (only repos both user and app can access). GitHub App user tokens can expire (~8h): API returns 409 github_reauth_required.
- PKCE with GitHub is sent as S256; verify GitHub honours it for your app type when testing live.
- Deployment: Vercel + Render are different sites, so SameSite=Lax cookies won't be sent on XHR. Plan: proxy /api through Vercel rewrites (same-origin) — to be documented in DEPLOYMENT.md.
- Role mapping: GitHub repo permissions.admin -> "owner", else "member".
- Webhook payload limit is MAX_REQUEST_BYTES (2 MB default); GitHub caps deliveries at 25 MB but PR/installation payloads are far smaller.
- Thread-based job timeouts are lease-based (a hung handler cannot be killed); handlers must check deadlines cooperatively.
- Cancellation only applies to queued jobs.
- Frontend dev uses a Vite proxy so the browser only talks to :5173; set GITHUB_REDIRECT_URI to the BACKEND callback (http://localhost:8000/api/v1/auth/github/callback) and FRONTEND_URL=http://localhost:5173.
- Frontend package versions are pinned from memory of compatible releases and are unverified; `npm install` may require adjusting a pin.
- UI is unverified visually (never rendered).
- Diff for real PRs is fetched live from GitHub per request (no caching yet) and needs the GitHub App configured.
- Severity counts exclude dismissed findings. Review polling interval: 4-5 s while queued/processing.
- Inline findings are matched by end_line on the new-file side only.
- Evidence verification makes findings conservative: a correct finding quoted imprecisely by the model is discarded (counted in the summary).
- Whole-file and cross-file context are not fetched yet (diff-only review); retrieved context plumbing exists (prompts) but is fed in Phase 9.
- LangChain `with_structured_output` behaviour/version compatibility is unverified.
- Prompt-injection safeguards are layered (untrusted wrapping, evidence/file/line validation, no tools, no execution) but not a guarantee.
- Comments are posted as the GitHub App (bot) identity; they cannot be deleted from SYNAXYS once published.
- GitHub App needs "Pull requests: Read & write" (and Contents: Read, Metadata: Read) — document in README/DEPLOYMENT.
- The GitHub review/comment payload shape (line/side/start_line/start_side, commit_id) follows GitHub's documented REST API but was never exercised against GitHub.
- Dismissing a finding (status 'dismissed') is only possible via comment cancel today; no separate finding-dismiss endpoint.
- Indexed code text (<=1500 chars/chunk, secrets excluded) is stored in Pinecone metadata and chunks are sent to OpenAI for embedding — document in SECURITY.md/privacy notes.
- Only the default branch is indexed; the branch filter is accepted by the API but the UI offers repository + language only.
- Serverless Pinecone: prefix `list` is used for per-file cleanup (delete-by-filter is not available there). Verify against your index type.
- GitHub tree API accepts a commit SHA in practice; truncated trees (very large repos) are refused rather than partially indexed.
- Memory vector backend + hash embeddings exist only for local demo/tests (API and worker are different processes, so it is not usable end-to-end across them).
- "Navigate to related PRs" from search results is not implemented.
- Baseline migration 0001 uses create_all from current metadata; 0002 is idempotent.
- The e2e mock mirrors the backend's response shapes by hand; if an endpoint changes, update e2e/mockApi.js (contract drift is possible and untested).
- Audit log shows only action/target/time to the user (meta is not exposed).
- Settings has no per-user preferences beyond theme (none are specified).
- UI has never been rendered or checked for accessibility in a real browser.
- render.yaml / vercel.json were never applied; Render env-group syntax deliberately avoided (identical secrets must be entered on both services).
- No licence file and no security contact are provided (placeholders called out in README/SECURITY.md).
- Docs describe Docker only as "ships in the final batch".
- Compose is a local-development stack; production guidance is in DEPLOYMENT.md (container host section).
- CI has never run; npm ci needs a committed package-lock.json (first `npm install` creates it).

## NOT STARTED
Nothing from the 12 phases remains. Open items are the unverified runs above plus the unimplemented extras listed in TEST_REPORT.md section 4.

## Hotfix 1 — sign out did nothing in the UI (server returned 204)
- Cause: `frontend/src/app/AuthProvider.jsx` called `qc.clear()` before `setQueryData(['me'], null)`. `clear()` destroys the cached `['me']` query that the mounted `useQuery` observes, so the update never reached React and the UI stayed "signed in" although the server session was revoked.
- Fix: removed `qc.clear()` (new `dropSession()` = `setQueryData` + `removeQueries` for everything except `me`/`auth-config`), explicit `signedOut` state that resets on the next successful `/auth/me`, navigate to `/login`, and logout no longer pretends to sign out locally when the request fails (non-401 errors keep the user signed in and show a toast).
- Regression tests added: `frontend/src/app/AuthProvider.test.jsx` (5 tests). Status: **NOT RUN** (no npm/Vitest in the sandbox). Diagnosis is from reading the code, not from reproducing it in a browser. Checks executed: JS/JSX syntax (59 files) PASS, import/export + unused-import scan PASS.

## UI refresh 1 (themes, Geist Pixel Circle, header/sidebar/profile menu, split login, custom dropdowns)
- Themes: dark `#d1d1d1 #828383 #434343 #2b2b2b #141414 #030303`, light `#e0ddd5 #c8c4b9 #aca49c #e7663e #69605f #33272b` as CSS variables; added tokens `accent-ink` (readable accent text), `danger-fg`; status colours chosen per theme (palettes have none). Light theme is flat (cards = page colour, separated by borders) because the palette has no lighter neutral.
- Font: Geist Pixel Circle via `frontend/scripts/install-geist-pixel.mjs` (downloads from the official vercel/geist-font repo; runs before dev/build; never fails the build; OFL licence copied) — NOT the `geist` npm package (its peer dependency is Next.js). h1-h3, header, sidebar, logo wordmark use it; static single weight, no faux bold.
- Logo + SYNAXYS wordmark (pixel font); black logo inverted in dark mode (`dark:invert`); text-only fallback if the SVG is missing.
- Header: theme button with desktop hover/focus tooltip below ("Switch to dark/light mode"); profile button opens a popup with Settings link (desktop + mobile; Esc/outside click/route change close it); sign out is icon-only below `md`; page name is one line with ellipsis.
- Sidebar: collapsible on desktop and mobile; slide animation + content padding animation share the same duration/easing; desktop preference remembered; mobile drawer has overlay, Esc, scroll lock, focus management, `inert` when closed; Lucide icons at stroke 1.5.
- Login: two columns on lg+ (form left, animated illustrative showcase right, decorative/aria-hidden); mobile shows only an animated background behind the form; theme toggle on the page.
- Dropdowns: new `components/ui/Select.jsx` (trigger + options in ONE rounded container, same width as the trigger, flips upward when no room, keyboard/ARIA select-only combobox); every native `<select>` replaced (repositories, PR feed + review history, reviews, code search, rule dialog, review policy).
- Bugs found and fixed while building: z-index of the dropdown would have overlaid the mobile drawer; a test-readiness race; Buffer in a linted test; light-theme status colours below 4.5:1.
- Computed WCAG contrast: all text/background pairs >= 4.5:1 EXCEPT light muted text on `#c8c4b9` (3.5:1), dark muted text on `#2b2b2b` (3.7:1), light primary button text `#33272b` on `#e7663e` (4.3:1) and light muted on page bg (4.50:1, exactly at the limit) — consequences of the requested palettes.
- Verification: JSX syntax (71 files), import/export + unused-import scan, docs/repo checks, 99 dependency-free tests, offline run of the font installer (warns, exit 0), pure installer helpers. NOT RUN: Vitest (17 files incl. new Select/AppLayout/AuthProvider/font tests), eslint, vite build, Playwright, any browser rendering (all visual/animation behaviour is unverified), real font download.

## UI refresh 2 (login fixed one-screen layout, bolder wordmark)
- Login: removed the 4 feature tags from the showcase; page is locked to the viewport (`h-screen h-dvh overflow-hidden`, grid row `minmax(0,1fr)`); both columns are vertically centred with auto margins (`m-auto`, which never clips; each column scrolls only if the viewport is truly tiny). Showcase is compacted and hides its optional parts on short viewports (third card under 780px height, intro paragraph under 680px).
- Logo wordmark: login `text-2xl -> text-3xl`, sidebar `text-lg -> text-xl`; bolder via a thin text-stroke (`0.035em`, constant `BOLD` in `Logo.jsx`) because Geist Pixel has a single weight.
- Tests added/updated: LoginPage (fixed layout, no tags, centring, wordmark), AppLayout Logo. NOT RUN (no Vitest/browser); fit of the showcase on real screen sizes is estimated, not measured.

## Change 3 — sample-data sign-in removed from the login page (deploy readiness)
- Login page: the "Explore with sample data" button and its text are gone; GitHub is the only way in (`authService.demoLogin` removed). Test asserts no such control exists even if the server reports `demo_login: true`.
- Backend: `DEMO_LOGIN_ENABLED` now defaults to **false** (opt-in developer/e2e helper; endpoint `POST /auth/demo-login` still exists, always disabled in production). Test env sets it true; new test covers default-off and production-off.
- e2e: mocked flow now signs in through the real "Continue with GitHub" link (mock answers `/auth/github/login` with a 302 to `/auth/callback?status=success`); the optional real-backend spec uses the API helper.
- Docs: README rewritten ("What needs credentials", demo quick-start steps removed), TESTING/API/DEPLOYMENT updated; new `docs/PRODUCTION_CHECKLIST.md` (ordered go-live steps, required values, smoke test, operations, never-verified list, not-implemented list). `package.json` gains `@testing-library/dom` (peer dependency of RTL 16). check_docs allow-lists `frontend/package-lock.json` (created by the user's `npm install`).
- NOT RUN: Vitest/pytest/e2e/eslint/build/browser; everything else unchanged.

## Batch 13 — Phase 1: core security and reliability (distributed rate limiting, Sentry, headers/CSP, admin job screen, cleanup, scanning)
Decisions (from the owner): independent workspaces later (Phase 4); admins = `ADMIN_GITHUB_IDS` allow-list; Redis for rate limiting; proprietary licence (Phase 5); Sentry. Operations guide: `docs/PHASE1_OPERATIONS.md`; credential runbook: `docs/KEY_ROTATION.md`.
- **Rate limiting**: `DistributedLimiter` (Redis MULTI/EXEC `SET NX EX` + `INCR` + `TTL`, fixed window) with circuit breaker and failure mode `memory|closed|open`; global per-IP limit and per-user limit on all routes except health and the GitHub webhook (deliberately unlimited by IP); `TRUSTED_PROXY_HOPS`. In-memory limiter kept (dev/tests/fallback).
- **Sentry**: API + worker + browser, DSNs from env, scrubbing of bodies/cookies/headers/query strings/locals/source/user data/secrets, no auto-enabled integrations, job-failure + 5xx-upstream + DB-connectivity capture, request/job ids in logs.
- **Headers/CSP**: API headers module; SPA headers + Report-Only CSP in `frontend/vercel.json` and `frontend/nginx.conf` (nginx per-location header inheritance bug fixed); inline theme script moved to `frontend/public/theme-init.js`.
- **Admin**: `GET/POST /api/v1/admin/jobs...` (404 for non-admins), real queue data, id-only payload allow-list, atomic retry with audit; UI at `/app/admin/jobs`; `is_admin` in `/auth/me`.
- **Cleanup**: `services/retention.py` scheduled in the worker (advisory lock) + `python -m app.scripts.cleanup [--dry-run]`; migration `0003_retention_indexes` (idempotent) + model indexes.
- **Scanning**: `.github/workflows/security.yml` (Semgrep, Gitleaks), `.github/dependabot.yml`, `.gitleaks.toml`; CI gets a Redis service for the real-Redis test.
- **Related fixes**: `api/v1/github.py` answers `github_reauth_required` (409) instead of 500 when a stored token cannot be decrypted (after a key change); `.gitignore` rewritten (LF; `.env.*`, keys, databases, test output); `backend/tools/make_source_zip.py` builds safe archives; `frontend/.env.example` added (required by `check_repo.py`, was missing).
- **Executed**: `python backend/tools/run_pure_tests.py` **PASS 114/114** (99 original + 15 new); `check_docs` PASS; `check_repo` PASS (after removing the dev database from the working copy); `check_names` PASS; `check_imports` PASS; `gen_api_docs` regenerated (43 endpoints); `compileall` PASS; frontend scrub logic executed with Node (assertions PASS); `make_source_zip.py` executed on the original tree (excluded the database, caches and test output).
- **NOT RUN** (no network/packages/Docker/Redis/Sentry in the sandbox): `pytest` (including new `test_phase13_db.py`, `test_phase13_redis.py`), ruff, alembic 0003, Vitest (incl. `monitoring.test.js`), eslint, vite build with `@sentry/react`, Playwright, YAML validation of workflows/compose/render, Docker, real Redis, Sentry delivery, CSP in a browser, Semgrep/Gitleaks runs, Render/Vercel behaviour. Versions of `redis`, `sentry-sdk` (ranges) and `@sentry/react` 8.47.0 were chosen from memory and could not be installed.

## Batch 14 — Phase 2: review workflow (search PR links, finding dismissal, queued-review cancel, GitHub comment deletion)
Guide: `docs/PHASE2_WORKFLOW.md`. Migration `0004_review_workflow` (idempotent). 4 new endpoints (47 total).
- **Dismissal**: independent of comments; who/when/why stored; carried across reviews of the same PR (fingerprint or same code with moved lines); pending comments auto-cancelled; restore.
- **Cancel**: real queue cancel (`job_queue.cancel`, atomic, `commit=False` option); review row updated in the same transaction; race answers 409; audit + `cancelled_by/at`.
- **Delete GitHub comment**: ownership verified (repo, PR, marker, bot author), delete + re-fetch confirmation, state `deleted` (row kept), attempts + audit.
- **Search**: `pull_request` on hits from stored GitHub URLs only; repo/branch/commit shown. Branch selector deferred to Phase 3 (needs multi-branch indexing).
- **Executed**: `run_pure_tests.py` **PASS 119/119** (114 + 5 new in `test_phase14_pure.py`); `check_docs`, `check_repo`, `check_names`, `check_imports` PASS; `gen_api_docs` (47 endpoints); crude bracket-balance check of edited JSX; pure logic smoke tests.
- **NOT RUN**: `pytest` incl. `test_phase14_db.py` (dismiss/cancel/delete API tests with a fake GitHub), alembic `0004`, Vitest incl. `ReviewWorkflow.test.jsx`, eslint, vite build, Playwright, real GitHub deletion, browser UI. Existing tests were not re-run (they need packages), so regressions in them are unverified; I only checked that none of them reference the strings I changed.

## Batch 15 — Phase 3: scalable, branch-aware, incremental indexing (+ search branch selector)
Guide: `docs/PHASE3_INDEXING.md` (read its "Upgrade" section: one-time re-embedding of existing indexes). Migration `0005_branch_indexing` (new tables `indexed_branch_files`, `branch_index_states`, `indexing_batches`; copies old rows; drops `indexed_files`; not downgradable). 4 new index endpoints + `GET /code-search/branches` (51 total).
- **Branch-aware**: per-branch state, vector ids `<branchtag>:<pathhash>#<n>`, namespace stays `repo-<id>`, branch filter always applied and re-checked, push webhooks refresh tracked branches, branch-delete events remove only that branch, `missing` branches are marked (never auto-deleted), `INDEX_MAX_BRANCHES`.
- **Large repositories**: truncated trees listed directory by directory (pruning excluded dirs; incomplete listing never deletes), priority ranking instead of alphabetical cut, `.gitignore` + per-repo include/exclude globs + per-repo max files, persisted batches, per-batch failure + "Continue", time-slice continuation, embedding budget per run, deterministic stale-chunk deletion (no per-file list calls).
- **UI**: search Branch selector (graceful note for unknown branches); Repositories page "Branches" panel (state per branch, index another branch from GitHub's live list, continue partial, remove).
- **Existing tests changed on purpose**: `test_phase9_db.py` (the "truncated tree is refused" assertion no longer holds; failure-recording kept), `test_foundation.py` (table count 18 -> 20).
- **Executed**: `run_pure_tests.py` **PASS 129/129** (119 + 10 new in `test_phase15_pure.py`); `check_docs`, `check_repo`, `check_names`, `check_imports` PASS; `gen_api_docs` (51 endpoints); bracket-balance check of edited JSX; smoke tests of gitignore/tree-walk/plan/batches.
- **NOT RUN**: `pytest` (incl. `test_phase15_db.py`: isolation, truncated tree, partial/retry, budget, deadline, missing branch, legacy upgrade, branch API, push webhook), alembic `0005` (data copy on SQLite/PostgreSQL), Vitest (`BranchIndexPanel.test.jsx`), eslint, vite build, real GitHub/OpenAI/Pinecone, browser UI. All earlier DB tests remain unexecuted too.

## Batch 16 — Phase 4: workspaces, roles, invitations, notifications, account deletion and export
Guide: `docs/PHASE4_WORKSPACES.md` (read "Upgrade": existing access is converted into workspaces without widening it). Migration `0006_workspaces` (new tables `workspaces`, `workspace_members`, `workspace_invitations`, `notifications`, `data_exports`; `repositories.workspace_id`, `audit_logs.workspace_id`; data conversion; not downgradable). 24 new endpoints (75 total).
- **Design**: workspace membership is the source of truth; `repository_access` is DERIVED for workspace repositories (`workspace_service.sync_access`), so every existing authorization query keeps working and respects workspace boundaries. GitHub sync no longer grants access to workspace repositories. `X-Workspace-Id` (verified on every request) only narrows lists.
- **Roles/RBAC** (backend-enforced, non-members get 404): owner / admin / member; invitations by GitHub login with one-time hashed token + login-bound acceptance, 7-day expiry; role change (owner only), removal, leave, ownership transfer, workspace delete (typed name), workspace audit.
- **Notifications**: in-app, polled; review completed / findings generated / review failed / indexing finished-partial-failed / invitations / workspace activity / export; per-user dedup; bell with unread count + notification page; read / read-all.
- **Account**: data export job (ZIP in DB, owner-only authenticated download, 24 h expiry, no credentials) and account deletion (typed login + session < 15 min, ownership handover or workspace dissolution, token + sessions + personal data removed, anonymous audit event, best-effort GitHub token revocation).
- **Retention** now also deletes expired exports, old invitations and old notifications. Settings added: `EXPORT_TTL_HOURS`, `RETENTION_INVITATIONS_DAYS`, `RETENTION_NOTIFICATIONS_DAYS`, `RETENTION_NOTIFICATIONS_MAX_DAYS`.
- **Existing tests changed on purpose**: `test_foundation.py` (table count 20 -> 25). The e2e mock API gained `/workspaces`, `/notifications/unread-count`, `/code-search/branches`.
- **Executed**: `run_pure_tests.py` **PASS 139/139** (129 + 10 new in `test_phase16_pure.py`); `check_docs`, `check_repo`, `check_names`, `check_imports` PASS; `gen_api_docs` (75 endpoints); bracket-balance check of edited JSX; legacy-access grouping verified for "nobody gains access".
- **NOT RUN**: `pytest` (incl. `test_phase16_db.py`: isolation, invitations, RBAC, access sync, notifications, export, deletion), alembic `0006` (data conversion), Vitest (incl. `Workspaces.test.jsx`), eslint, vite build, Playwright, real GitHub token revocation, browser UI. Earlier DB tests also remain unexecuted; Phase 4 touches login, connect and sync flows they exercise (e.g. `test_phase9_db.py`, `test_phase4_db.py`), so please run the whole suite.

## Batch 17 — Phase 5: favicon, licence, security policy, Privacy Policy, Terms of Service
Guide: `docs/PHASE5_TRUST.md`; placeholder checklist: `docs/legal/PLACEHOLDERS.md`. No migration, no new endpoints (75).
- **Favicon**: derived from the existing logo (not redrawn): SVG (dark-mode aware, ~1 KB instead of 39 KB), ICO 16/32/48, PNG 16/32/180/192/512, maskable 512, `site.webmanifest`, head tags; generator `backend/tools/make_favicons.py`. Checked visually in a rendered contact sheet.
- **Legal documents** (drafts with `[[placeholders]]`, nothing invented): Privacy Policy (real data flows: OpenAI + Pinecone disclosure, storage, cookies, processors, retention table checked against settings, export/deletion, GitHub permissions), Terms of Service, vulnerability-reporting policy, proprietary licence notice; single source `frontend/src/legal/*.json`, public pages `/legal/*`, Markdown + checklist generated by `backend/tools/gen_legal_docs.py`; footer links on sign-in and app pages, Settings -> Legal.
- **LICENSE** (proprietary notice with placeholders), `package.json` `"license": "UNLICENSED"`, README, new "Reporting a vulnerability" section at the top of `SECURITY.md` with placeholder contacts, `docs/security.txt.template` (deliberately NOT published).
- **Behaviour fix**: deleting a workspace / the account of its only member now purges the repositories' reviews, findings, comments and index state (`purge_repositories`) instead of leaving them orphaned; UI/doc wording updated.
- **Executed**: `run_pure_tests.py` **PASS 151/151** (139 + 12 new in `test_phase17_pure.py`: favicon sizes/ICO header/manifest/html references, legal structure, no invented e-mail/URL/phone/company, required disclosures present, no false reassurance, retention table vs defaults, Markdown in sync, licence and SECURITY.md checks); `check_docs`, `check_repo` (now also requires the new files), `check_names`, `check_imports` PASS; JSON validity via Node; bracket check of edited JSX (the new test file trips the crude checker on regex literals only).
- **NOT RUN**: Vitest (`Legal.test.jsx`, plus everything from earlier phases), eslint, vite build, Playwright, `pytest` (incl. the workspace-purge assertions in `test_phase16_db.py`), real browser rendering of favicon/pages/CSP, any lawyer review.

