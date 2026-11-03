"""Static inspection: every `from app.x import name` must resolve to a real module + top-level name."""
import ast, pathlib, sys
root = pathlib.Path("/home/claude/synaxys/backend"); bad = []
def top_names(path):
    t = ast.parse(path.read_text()); names = set()
    for n in t.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): names.add(n.name)
        elif isinstance(n, ast.Assign): names |= {x.id for x in n.targets if isinstance(x, ast.Name)}
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name): names.add(n.target.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)): names |= {(a.asname or a.name).split(".")[0] for a in n.names}
    return names, any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names) for n in t.body)
for f in root.rglob("*.py"):
    if "__pycache__" in f.parts: continue
    for n in ast.walk(ast.parse(f.read_text())):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("app"):
            mod = root / n.module.replace(".", "/")
            target = mod.with_suffix(".py") if mod.with_suffix(".py").exists() else mod / "__init__.py"
            if not target.exists(): bad.append(f"{f.name}: missing module {n.module}"); continue
            names, star = top_names(target)
            sub = {p.stem for p in mod.glob("*.py")} if mod.is_dir() else set()
            for a in n.names:
                if a.name != "*" and a.name not in names and a.name not in sub and not star:
                    bad.append(f"{f.relative_to(root)}: {n.module}.{a.name} not defined")
print("\n".join(bad) or "all internal imports resolve"); sys.exit(1 if bad else 0)
