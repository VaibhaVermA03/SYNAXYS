"""Poor-man's pyflakes F821 (undefined name) check using only the stdlib `symtable`.
Every name a function/class/comprehension reads from the global scope must be defined at module level,
imported, or a builtin. Catches missing imports and typos. Run from the repo root: python backend/tools/check_names.py"""
import builtins
import pathlib
import symtable
import sys

ROOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parents[1]
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__", "__spec__"}
problems = []


def walk(table, module_names, path):
    for sym in table.get_symbols():
        if table.get_type() != "module" and sym.is_referenced() and sym.is_global() and sym.get_name() not in module_names | BUILTINS:
            problems.append(f"{path}:{table.get_lineno()} undefined name '{sym.get_name()}' in {table.get_name()}")
    for child in table.get_children():
        walk(child, module_names, path)


files = [f for f in ROOT.rglob("*.py") if "__pycache__" not in f.parts and ".venv" not in f.parts]
for f in sorted(files):
    src = f.read_text()
    top = symtable.symtable(src, str(f), "exec")
    names = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
    if any(s.get_name() == "*" for s in top.get_symbols()):
        names |= {"*"}
    if f.name == "__init__.py" and "import *" in src:
        continue
    walk(top, names, f.relative_to(ROOT))
unique = sorted(set(problems))
print("\n".join(unique) or f"no undefined names in {len(files)} Python files")
sys.exit(1 if unique else 0)
