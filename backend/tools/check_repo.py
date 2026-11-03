"""Final repository inspection (stdlib only). Run from the repo root: python backend/tools/check_repo.py
 1. no secrets / forbidden artifacts   2. required files exist   3. frontend API calls (and the e2e mock) match real backend routes"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
problems: list[str] = []
SKIP_DIRS = {"node_modules", "__pycache__", ".git", "dist", ".venv", "playwright-report", "test-results"}
files = [f for f in ROOT.rglob("*") if f.is_file() and not (SKIP_DIRS & set(f.relative_to(ROOT).parts))]

# ---- 1. secrets and forbidden artifacts
FORBIDDEN = [r"(^|/)\.env$", r"(^|/)\.env\.(?!example)", r"\.pem$", r"\.sqlite3?$", r"\.zip$", r"\.heartbeat$", r"id_rsa"]
SECRET_PATTERNS = {
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"), "GitHub PAT": re.compile(r"github_pat_[A-Za-z0-9_]{50,}"),
    "OpenAI key": re.compile(r"sk-[A-Za-z0-9_\-]{30,}"), "Pinecone key": re.compile(r"pcsk_[A-Za-z0-9_]{20,}"),
    "AWS key id": re.compile(r"AKIA[0-9A-Z]{16}"), "PEM body": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----\s*[A-Za-z0-9+/=]{40,}"),
}
KNOWN_FAKES = {"AKIAABCDEFGHIJKLMNOP"}  # the placeholder used in redaction tests
for f in files:
    rel = f.relative_to(ROOT).as_posix()
    if any(re.search(p, rel) for p in FORBIDDEN):
        problems.append(f"forbidden file present: {rel}")
        continue
    try:
        text = f.read_text()
    except UnicodeDecodeError:
        continue
    for name, rx in SECRET_PATTERNS.items():
        for m in rx.finditer(text):
            if m.group(0) not in KNOWN_FAKES:
                problems.append(f"possible {name} in {rel}: {m.group(0)[:12]}…")

# ---- 2. required files (from the build specification)
REQUIRED = """README.md SECURITY.md DEPLOYMENT.md TESTING.md MANIFEST.md IMPLEMENTATION_STATUS.md TEST_REPORT.md .gitignore .env.example docker-compose.yml render.yaml
backend/.env.example backend/Dockerfile backend/requirements.txt backend/requirements-dev.txt backend/alembic.ini backend/pytest.ini backend/ruff.toml backend/migrations/env.py
backend/migrations/versions/0001_initial_schema.py backend/migrations/versions/0002_indexed_files.py backend/app/main.py backend/app/db/seed.py backend/app/core/config.py
backend/app/api/router.py backend/app/workers/runner.py backend/app/workers/review_worker.py backend/app/workers/indexing_worker.py backend/app/workers/publish_worker.py
backend/app/services/github_service.py backend/app/services/vector_service.py backend/app/agents/review_graph.py backend/app/agents/prompts.py backend/app/agents/review_policies.py
frontend/package.json frontend/vite.config.js frontend/tailwind.config.js frontend/index.html frontend/.env.example frontend/Dockerfile frontend/nginx.conf frontend/vercel.json
frontend/playwright.config.js frontend/src/main.jsx frontend/src/App.jsx frontend/public/brand/README.md frontend/public/brand/.gitkeep frontend/e2e/review-flow.spec.js
docs/ARCHITECTURE.md docs/API.md docs/API_ENDPOINTS.md docs/GITHUB_SETUP.md docs/PINECONE_OPENAI.md docs/TROUBLESHOOTING.md .github/workflows/ci.yml""".split()
problems += [f"required file missing: {r}" for r in REQUIRED if not (ROOT / r).exists()]
for api in "auth github webhooks repositories pull_requests reviews review_rules code_search dashboard settings health".split():
    if not (ROOT / f"backend/app/api/v1/{api}.py").exists():
        problems.append(f"required router missing: {api}.py")

# ---- 3. contract: frontend -> backend
def norm(p: str) -> str:
    p = p.split("?")[0]
    return re.sub(r"\{[^}]*\}|\$\{[^}]*\}|(?<=/)\d+(?=/|$)", "{}", p)

backend = set()
for f in (ROOT / "backend/app/api/v1").glob("*.py"):
    tree = ast.parse(f.read_text())
    prefix = next((kw.value.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "APIRouter"
                   for kw in n.value.keywords if kw.arg == "prefix"), "")
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for d in fn.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and getattr(d.func.value, "id", "") == "router" and d.func.attr in ("get", "post", "patch", "delete", "put"):
                backend.add((d.func.attr.upper(), norm(prefix + (d.args[0].value if d.args else ""))))

svc = (ROOT / "frontend/src/services/index.js").read_text()
front = set()
for m in re.finditer(r"api\(\s*([`'\"])(.+?)\1(?:\s*,\s*\{(.*?)\})?\s*\)", svc):
    method = re.search(r"method:\s*'(\w+)'", m.group(3) or "")
    front.add(((method.group(1) if method else "GET").upper(), norm(m.group(2))))
for method, path in sorted(front - backend):
    problems.append(f"frontend calls {method} {path} but the backend has no such route")

# e2e mock must only answer routes that exist (GET assumed unless it is an unsafe-looking action)
mock = (ROOT / "frontend/e2e/mockApi.js").read_text()
backend_paths = {p for _, p in backend}
for m in re.finditer(r"path === '([^']+)'", mock):
    if norm(m.group(1)) not in backend_paths:
        problems.append(f"e2e mock handles {m.group(1)} which is not a backend route")

print("\n".join(problems) or f"repo OK: {len(files)} files, {len(REQUIRED)} required files present, no secrets, {len(front)} frontend calls ⊆ {len(backend)} backend routes")
sys.exit(1 if problems else 0)
