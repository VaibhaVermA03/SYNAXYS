"""Generate docs/API.md from the real route decorators (stdlib only). Run from the repo root:
    python backend/tools/gen_api_docs.py
Never edit docs/API.md by hand; regenerate it."""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
API = ROOT / "backend/app/api/v1"
PUBLIC = {("GET", "/health"), ("GET", "/health/ready"), ("GET", "/auth/config"), ("GET", "/auth/github/login"), ("GET", "/auth/github/callback"), ("POST", "/auth/demo-login"), ("POST", "/auth/logout")}
rows = []
for f in sorted(API.glob("*.py")):
    tree = ast.parse(f.read_text())
    prefix = ""
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "APIRouter":
            for kw in n.value.keywords:
                if kw.arg == "prefix":
                    prefix = kw.value.value
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for d in fn.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("get", "post", "patch", "delete", "put") and getattr(d.func.value, "id", "") == "router":
                method, path = d.func.attr.upper(), prefix + (d.args[0].value if d.args else "")
                status = next((k.value.value for k in d.keywords if k.arg == "status_code"), 200)
                src = ast.unparse(fn.args)
                if "webhooks" in f.name:
                    auth = "HMAC signature (`X-Hub-Signature-256`)"
                elif (method, path) in PUBLIC:
                    limited = "limit_auth" in ast.unparse(d) or any("limit_auth" in ast.unparse(x) for x in fn.decorator_list)
                    auth = "Public (rate-limited)" if limited else "Public (session optional)" if path == "/auth/logout" else "Public"
                elif "current_user" in src or "current_session" in src:
                    auth = "Session cookie" + (" + CSRF header" if method != "GET" else "")
                else:
                    auth = "Session cookie"
                doc = (ast.get_docstring(fn) or "").split("\n")[0]
                rows.append((path, method, status, auth, doc, f.name))
rows.sort(key=lambda r: (r[0], r[1]))
out = ["# API reference", "", "_Generated from the route decorators by `backend/tools/gen_api_docs.py` — do not edit by hand._", "",
       "Base path: `/api/v1`. Interactive OpenAPI docs are served at `/docs` when `APP_ENV` is not `production`.", "",
       "| Method | Path | Success | Auth | Notes |", "|---|---|---|---|---|"]
out += [f"| {m} | `/api/v1{p}` | {s} | {a} | {d} |" for p, m, s, a, d, _ in rows]
out.append("")
out.append(f"_{len(rows)} endpoints._")
(ROOT / "docs").mkdir(exist_ok=True)
(ROOT / "docs/API_ENDPOINTS.md").write_text("\n".join(out) + "\n")
print(f"{len(rows)} endpoints written to docs/API_ENDPOINTS.md")
