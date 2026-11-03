# Test report

Generated 2026-10-26 in the build sandbox (Python 3.12.3, Node 22.22.2, **no internet, no Docker, no browser**). Source size: backend Python 7501 lines, frontend JS/JSX 3170 lines, 14 markdown files.

**Read this first:** the only things that actually ran are the dependency-free checks in section 1. The real test suites, the frontend build, the database migrations, Docker, CI, and every call to GitHub / OpenAI / Pinecone are **NOT RUN** (section 2). Passing section 1 does **not** mean the application works; it means the code is syntactically valid, internally consistent, free of undefined names/missing imports, and that its dependency-free logic tests pass.

## 1. Executed checks

| Check | Command | Result | Evidence (last output line) |
|---|---|---|---|
| Dependency-free test suite | `python3 backend/tools/run_pure_tests.py` | **PASS** | 99 passed, 0 failed (9 modules) |
| Docs ↔ settings/scripts/paths | `python3 backend/tools/check_docs.py` | **PASS** | docs consistent (10 doc files, 53 settings) |
| Undefined names (symtable) | `python3 backend/tools/check_names.py` | **PASS** | no undefined names in 112 Python files |
| Internal Python imports resolve | `python3 backend/tools/check_imports.py` | **PASS** | all internal imports resolve |
| Frontend JS: imports/exports resolve, no unused imports (sandbox script) | `ad-hoc script (not shipped)` | **PASS** | 57 JS files: relative imports/exports resolve, no unused imports |
| JS/JSX syntax of every frontend file (TypeScript parser, sandbox) | `ad-hoc script (not shipped)` | **PASS** | 58 files checked, 0 syntax errors |
| Python compiles | `py_compile on every .py` | **PASS** | 112 files |
| YAML/JSON configs parse | `yaml.safe_load / json.load` | **PASS** | docker-compose.yml, render.yaml, .github/workflows/ci.yml, frontend/package.json, frontend/vercel.json |
| API reference current + complete | `gen_api_docs.py vs raw decorator count` | **PASS** | 39 endpoints in table, 39 route decorators |
| Markdown relative links | `regex over all docs` | **PASS** | all resolve |

**Negative controls (checks proven able to fail):** `check_names.py` reported both planted undefined names (exit 1); `check_repo.py` reported a planted OpenAI-style key, a fake frontend route call, a non-existent route in the e2e mock, and a bogus call with a template path (exit 1); both were reverted and re-run clean.

**What the 99 dependency-free tests cover:** webhook HMAC verification; secret detection/redaction (including secrets split across chunks and multi-line keys); unified-diff parsing and single-hunk line validation; PKCE (RFC 7636 vector), signed state, CSRF, session-token hashing; rate limiter; GitHub retry/backoff/rate-limit/pagination and a fake-HTTP GitHub client (no auto-retry on POST, repo-name traversal rejection, content API validation); webhook payload validation and routing; job backoff/staleness/retry classification; rule validation; review context selection, batching, prompt-injection wrapping, finding validation (evidence, lines, dedup, caps), end-to-end pipeline with a scripted model, provider-error mapping; publish rules (markers, payloads, blockers, transitions); chunking, index planning, vector-store namespace isolation, hash embedder, search logic, cross-file retrieval isolation; integration-status secret non-leakage; DATABASE_URL normalisation.

## 2. NOT RUN (unverified) — and how to run them

| Area | Command | Why not run here |
|---|---|---|
| Backend API + DB tests (67 tests: OAuth, sessions/CSRF, tenant isolation, webhooks/idempotency, queue/worker, review execution, approval/publishing, indexing/search, settings, production guards, key rotation) | `cd backend && pip install -r requirements-dev.txt && pytest -x` | fastapi, sqlalchemy, cryptography, pydantic not installable offline |
| Ruff | `cd backend && ruff check .` | not installed |
| Alembic migrations 0001/0002, seed | `cd backend && alembic upgrade head && python -m app.db.seed` | SQLAlchemy/Alembic not installed |
| Frontend unit/component tests (17 files) | `cd frontend && npm install && npm test` | no npm registry access |
| ESLint, production build | `npm run lint && npm run build` | same |
| Playwright e2e (4 tests) | `npm run e2e:install && npm run e2e` (+ `E2E_BACKEND=1` for the real-backend spec) | no browser/packages |
| Dependency audits | `cd backend && pip-audit -r requirements.txt` · `cd frontend && npm audit` | no network |
| Lockfiles | `npm install` generates `frontend/package-lock.json`; `pip freeze` if you want a Python lock | no network; **no lockfile is included** |
| Docker images and Compose stack | `docker compose config -q && docker compose build && docker compose up` | no Docker |
| CI workflow | push to GitHub | not executed |
| Real integrations | GitHub OAuth/App/webhooks, review comment posting, OpenAI structured output + embeddings, Pinecone upsert/query/delete, PostgreSQL `SKIP LOCKED` under concurrency | no credentials/network |
| Deployment | Render blueprint, Vercel rewrite | never applied |
| Visual/UX/accessibility | open the app in a browser; run an a11y audit | no browser |

## 3. Problems the checks found and fixed during the build

* Repository-name validator accepted `../x` (URL path traversal) — fixed, regression-tested.
* Secrets in a long line could be split across chunk fragments and evade detection before embedding — detection now runs on the whole file.
* Evidence containing a secret failed the redacted-diff match; long comments lost the AI-disclaimer footer — fixed.
* A repository's second disconnect never queued vector cleanup (permanent dedup key) — `enqueue_or_requeue`.
* 23 settings were undocumented and a required `backend/.env.example` was missing; the API table generator skipped async routes — fixed (docs/code checkers now guard this).
* Several test-fixture and test-expectation mistakes were corrected (not code bugs): an RFC vector typo, delimiter count, duplicate keyword.

## 4. Known limitations

See [SECURITY.md](SECURITY.md) (per-process rate limiting, data sent to OpenAI/Pinecone, no account deletion, AI findings are suggestions and prompt injection cannot be fully eliminated, no SAST integration) and the caveat lists in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). Not implemented: related-PR navigation from search, branch selector in search UI, finding-level dismissal (only comment dismissal), partial indexing of GitHub-truncated trees, per-user preferences beyond theme.

## 5. External credentials checklist

| Needed for | Items |
|---|---|
| Sign-in and repository access | GitHub App: App ID, slug, client ID + secret, private key (.pem), webhook secret; app installed on the target account/org |
| Secrets at rest | `ENCRYPTION_KEY` (Fernet), `APP_SECRET_KEY` |
| AI review + embeddings | `OPENAI_API_KEY` |
| Code search | `PINECONE_API_KEY` + a serverless cosine index whose dimension equals `EMBEDDING_DIMENSIONS` |
| Production | PostgreSQL URL, HTTPS domains for frontend (Vercel) and API (Render), a Render worker instance |
