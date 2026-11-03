"""Run the tests that need NO third-party packages (stdlib only), without pytest:
    python backend/tools/run_pure_tests.py
These are the checks that were actually executed while the project was generated. The full suite needs
`pip install -r backend/requirements-dev.txt` and `pytest` (see TESTING.md)."""
import importlib
import pathlib
import sys
import traceback

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
mods = ["test_core_pure", "test_foundation"] + sorted(p.stem for p in (BACKEND / "app/tests").glob("test_phase*_pure.py"))
ok = bad = 0
for name in mods:
    m = importlib.import_module(f"app.tests.{name}")
    for fn in sorted(n for n in dir(m) if n.startswith("test_")):
        try:
            getattr(m, fn)(); ok += 1
        except Exception:  # noqa: BLE001
            bad += 1; print(f"FAIL {name}.{fn}"); traceback.print_exc()
print(f"{ok} passed, {bad} failed ({len(mods)} modules)")
sys.exit(1 if bad else 0)
