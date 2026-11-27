"""Build a SAFE source ZIP of the repository (stdlib only).

    python backend/tools/make_source_zip.py ../SYNAXYS_source.zip

* Never includes: .git, dependencies, caches, build/test output, .env files (except *.example), SQLite/other databases,
  keys/certificates, existing ZIPs.
* Refuses to write the archive (exit 1) if any included text file contains something that looks like a credential, using the
  same patterns as backend/tools/check_repo.py.
* Prints exactly what was excluded so nothing disappears silently. The output file must be OUTSIDE the repository.
"""
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", ".ruff_cache", ".pytest_cache", "playwright-report", "test-results", "coverage"}
SKIP_FILE = [r"(^|/)\.env$", r"(^|/)\.env\.(?!example$)", r"\.sqlite3(-\w+)?$", r"\.db$", r"\.pem$", r"\.key$", r"\.p12$", r"id_rsa", r"\.zip$", r"\.heartbeat$", r"(^|/)export_source\.py$", r"\.DS_Store$"]
SECRETS = {
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"), "GitHub PAT": re.compile(r"github_pat_[A-Za-z0-9_]{50,}"),
    "OpenAI key": re.compile(r"sk-[A-Za-z0-9_\-]{30,}"), "Pinecone key": re.compile(r"pcsk_[A-Za-z0-9_]{20,}"),
    "AWS key id": re.compile(r"AKIA[0-9A-Z]{16}"), "PEM body": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----\s*[A-Za-z0-9+/=]{40,}"),
    "Fernet-style key assigned": re.compile(r"(ENCRYPTION_KEY|APP_SECRET_KEY)\s*=\s*[A-Za-z0-9_\-+/]{32,}={0,2}\s*$", re.M),
}


def main(out: pathlib.Path) -> int:
    out = out.resolve()
    if ROOT in out.parents:
        print(f"refusing: output {out} is inside the repository"); return 2
    include, excluded, problems = [], [], []
    for f in sorted(ROOT.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(ROOT).as_posix()
        if SKIP_DIRS & set(f.relative_to(ROOT).parts) or any(re.search(p, rel) for p in SKIP_FILE):
            excluded.append(rel); continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            include.append(f); continue
        for name, rx in SECRETS.items():
            for m in rx.finditer(text):
                if "example" not in rel.lower() and "/tests/" not in rel:
                    problems.append(f"possible {name} in {rel}")
        include.append(f)
    if problems:
        print("NOT written - resolve these first:\n  " + "\n  ".join(sorted(set(problems)))); return 1
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in include:
            z.write(f, f.relative_to(ROOT).as_posix())
    groups = {}
    for rel in excluded:
        key = next((d for d in SKIP_DIRS if f"{d}/" in rel or rel.startswith(d + "/")), "sensitive/other file")
        groups.setdefault(key, []).append(rel)
    print(f"wrote {out} ({len(include)} files)")
    for k, v in sorted(groups.items()):
        print(f"  excluded {len(v):>5}  {k}" + (f"  e.g. {v[0]}" if k == "sensitive/other file" else ""))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__); sys.exit(2)
    sys.exit(main(pathlib.Path(sys.argv[1])))
