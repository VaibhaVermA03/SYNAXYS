"""Mechanical doc/code consistency checks (stdlib only). Run from the repo root: python backend/tools/check_docs.py

1. every Settings field has an entry in .env.example (and vice versa)
2. every `npm run <script>` / `python -m <module>` command mentioned in docs exists
3. every repo path written in `backticks` in the docs exists
"""
import ast
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
USER_CREATED = {"backend/.env", "frontend/public/brand/synaxys-logo.svg", "frontend/package-lock.json"}  # intentionally absent from the repository
problems: list[str] = []

# 1 --- settings <-> env example
tree = ast.parse((ROOT / "backend/app/core/config.py").read_text())
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings")
fields = {n.target.id.upper() for n in cls.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
for env_file in (ROOT / ".env.example", ROOT / "backend/.env.example"):
    if not env_file.exists():
        problems.append(f"missing {env_file.relative_to(ROOT)}")
        continue
    declared = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", env_file.read_text(), re.M))
    problems += [f"{env_file.name}: Settings field {f} is not documented" for f in sorted(fields - declared)]
    problems += [f"{env_file.name}: {d} is not a Settings field" for d in sorted(declared - fields)]

# 2/3 --- docs commands and paths
docs = [p for p in [ROOT / "README.md", ROOT / "SECURITY.md", ROOT / "DEPLOYMENT.md", ROOT / "TESTING.md", *sorted((ROOT / "docs").glob("*.md"))] if p.exists()]
scripts = set(json.loads((ROOT / "frontend/package.json").read_text())["scripts"])
for d in docs:
    text = d.read_text()
    for s in re.findall(r"npm run ([\w:-]+)", text):
        if s not in scripts:
            problems.append(f"{d.name}: npm script '{s}' does not exist")
    for mod in re.findall(r"python -m ([\w.]+)", text):
        if mod not in ("venv", "pip", "pytest", "uvicorn", "alembic") and not (ROOT / "backend" / (mod.replace(".", "/") + ".py")).exists():
            problems.append(f"{d.name}: python module '{mod}' not found")
    for p in re.findall(r"`((?:backend|frontend|docs|\.github)/[\w./\-]+)`", text):
        if p not in USER_CREATED and "*" not in p and "<" not in p and not (ROOT / p).exists() and not (ROOT / p.rstrip("/")).exists():
            problems.append(f"{d.name}: path `{p}` does not exist")
print("\n".join(problems) or f"docs consistent ({len(docs)} doc files, {len(fields)} settings)")
sys.exit(1 if problems else 0)
