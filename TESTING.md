# Testing

**Honest status:** the project was generated without network access. Only the dependency-free checks below were executed. Treat every **NOT RUN** row as unverified, and expect to fix small bugs the first time you run it.

## Status


| Suite | Where | Command | What it covers | Executed during generation? |
|---|---|---|---|---|
| Pure-Python tests (9 modules, 99 tests) | `backend/app/tests/test_core_pure.py`, `test_foundation.py`, `test_phase*_pure.py` | `python backend/tools/run_pure_tests.py` (or `pytest`) | HMAC verification, secret redaction, diff parsing + line validation, PKCE/CSRF/state tokens, rate limiter, GitHub retry/backoff/pagination, webhook payload validation, job policy, rule validation, review context + prompts + finding validation + pipeline with a scripted model, publish rules, chunking, secret-aware indexing plan, vector-store isolation, search/context retrieval, integration status | **PASS (99/99)** |
| Backend API / DB tests | `test_api_phase3.py` (13), `test_api_phase6.py` (6), `test_api_phase10.py` (3), `test_phase4_db.py` (10), `test_phase7_db.py` (7), `test_phase8_db.py` (12), `test_phase9_db.py` (11), `test_config_encryption.py` (5) | `cd backend && pytest` | OAuth state/PKCE/session/CSRF, tenant isolation, webhooks + idempotency, job queue + worker, review execution, approval/publishing safety, indexing + search isolation, production config guards, Fernet round-trip + key rotation, migrations + seed | **NOT RUN** (needs fastapi, sqlalchemy, cryptography…) |
| Frontend unit/component tests | `frontend/src/**/*.test.js(x)` (17 files) | `cd frontend && npm test` | API client + CSRF, route guard, login, repositories + indexing, PR feed, diff viewer, review detail + publishing flow, rules + tester, settings/integrations/policy, search, dashboard, error boundary | **NOT RUN** (no `npm install`) |
| End-to-end (mocked API) | `frontend/e2e/review-flow.spec.js` (3 tests) | `npm run e2e:install && npm run e2e` | sign-in → connect + index → PR diff → mocked AI review → approve → confirm → publish → search; protected routes; 404 | **NOT RUN** |
| End-to-end (real local backend) | `frontend/e2e/demo-backend.spec.js` (1 test) | `E2E_BACKEND=1 npm run e2e` | sign-in through the developer API helper (`DEMO_LOGIN_ENABLED=true`), labelled sample data, read-only review | **NOT RUN** |
| Lint / build | — | `cd backend && ruff check .` (config: `backend/ruff.toml`, correctness rules only) · `cd frontend && npm run lint && npm run build` | style, production bundle | **NOT RUN** |
| Migrations | `backend/migrations` | `cd backend && alembic upgrade head` (then `alembic downgrade base` on a scratch DB) | 0001 baseline + 0002 | **NOT RUN** |
| Dependency audit | — | `cd backend && pip-audit -r requirements.txt` · `cd frontend && npm audit` | known CVEs | **NOT RUN** |
| Docker / Compose | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` | `docker compose config -q && docker compose build && docker compose up` | images build, stack boots, migrations run | **NOT RUN** (YAML parses; nothing was built) |
| CI workflow | `.github/workflows/ci.yml` | push to GitHub | all of the above in CI | **NOT RUN** (YAML parses) |
| Static checks | — | see below | Python compile, internal import resolution, unused imports; JS/JSX syntax of every frontend file (TypeScript parser); relative import/export resolution; docs ↔ settings/scripts/paths | **PASS** (ad-hoc scripts during generation; `check_docs.py` is included) |

## Running everything locally

```bash
# backend
cd backend && python3.12 -m venv .venv && source .venv/bin/activate   # Windows: py -3.12 -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest -x                       # config in backend/pytest.ini
ruff check .
alembic upgrade head            # SQLite by default
pip-audit -r requirements.txt

# frontend
cd ../frontend
npm install                     # generates package-lock.json — commit it
npm test && npm run lint && npm run build && npm audit
npm run e2e:install && npm run e2e
```

The API tests build a fresh SQLite database per test and replace GitHub with in-test fakes; none of them contact GitHub, OpenAI or Pinecone, and no real credentials are needed or used. `conftest.py` fixtures: `ctx` (app + DB + fake OAuth GitHub), `login()` (runs the real OAuth callback against the fake).

## Interpreting failures

* The most likely first failures are version pins (`requirements.txt`, `package.json` were pinned from memory and never installed), ORM/SQLite quirks, and mock/contract drift between `frontend/e2e/mockApi.js` and the real API.
* A failing *security-property* test (tenant isolation, CSRF, publishing safety, secret leakage, webhook signature) should be treated as a release blocker, not a flaky test.
* Please keep tests honest: do not mark anything passed that was skipped.

## Consistency tools

| Tool | Purpose |
|---|---|
| `python backend/tools/check_docs.py` | every `Settings` field is in both `.env.example` files and vice-versa; every `npm run` script, `python -m` module and `backticked` repo path used in the docs exists |
| `python backend/tools/check_repo.py` | no secrets/forbidden files; required files exist; every call in `frontend/src/services/index.js` and every route in `frontend/e2e/mockApi.js` exists in the backend routers |
| `python backend/tools/check_names.py` | undefined names via `symtable` (stand-in for pyflakes F821; proven to detect planted errors) |
| `python backend/tools/check_imports.py` | every `from app… import name` resolves to a real module and name |
| `python backend/tools/gen_api_docs.py` | regenerates `docs/API_ENDPOINTS.md` from the route decorators (39 endpoints at generation time) |

## Not covered by any test

Real GitHub OAuth/App/webhook delivery and review posting; real OpenAI structured output and embeddings; real Pinecone upserts/queries/deletes; PostgreSQL-specific behaviour (`SKIP LOCKED`, concurrent workers); browser rendering, accessibility and responsive layout; load/performance; Render/Vercel deployment.
