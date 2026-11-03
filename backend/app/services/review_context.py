"""Pure helpers that decide WHAT is sent to the model: file eligibility, rule selection,
size-bounded batches and the line-numbered diff rendering. Secrets are redacted here."""
import fnmatch
import posixpath
import re
from dataclasses import dataclass

from app.core.security import redact_secrets

_SKIP_PATH_PARTS = ("node_modules/", "vendor/", "dist/", "build/", ".git/", "__pycache__/", "venv/", ".venv/", "target/", "coverage/")
_SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock", "Cargo.lock", "go.sum", "composer.lock", "uv.lock"}
_SKIP_SUFFIX = (".min.js", ".min.css", ".map", ".snap", ".lock")
_SECRET_FILES = {".env", "id_rsa", "id_ed25519", "credentials", ".npmrc", ".pypirc"}
_SECRET_SUFFIX = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore")

LANG_BY_EXT = {".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".ts": "typescript", ".tsx": "typescript",
               ".java": "java", ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php", ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp",
               ".hpp": "cpp", ".cs": "csharp", ".kt": "kotlin", ".swift": "swift", ".sql": "sql", ".sh": "shell", ".bash": "shell",
               ".html": "html", ".css": "css"}


def language_of(path: str) -> str | None:
    return LANG_BY_EXT.get(posixpath.splitext(path.lower())[1])


def path_exclusion_reason(path: str) -> str | None:
    """Path-only exclusions shared by reviewing and indexing (secrets, generated, vendored)."""
    base = posixpath.basename(path)
    low = path.lower()
    if base in _SECRET_FILES or base.startswith(".env") or low.endswith(_SECRET_SUFFIX):
        return "sensitive_file"
    if base in _SKIP_NAMES or low.endswith(_SKIP_SUFFIX):
        return "generated_or_lock"
    if any(part in "/" + low for part in ("/" + p for p in _SKIP_PATH_PARTS)):
        return "vendored_or_build"
    return None


def exclusion_reason(diff: dict) -> str | None:
    """Why a file must NOT be sent to the model (None = eligible)."""
    if diff.get("skipped_reason"):
        return diff["skipped_reason"]
    reason = path_exclusion_reason(diff["path"])
    if reason:
        return reason
    return "deleted_file" if diff.get("status") == "removed" else None


def glob_match(pattern: str, path: str) -> bool:
    """gitignore-ish glob: ** crosses directories, * and ? do not, {a,b} alternation. Case-sensitive."""
    pattern = pattern.strip()
    if not pattern:
        return False
    if "/" not in pattern:  # bare patterns like *.py match at any depth
        pattern = "**/" + pattern

    def translate(p: str) -> str:
        out, i = "", 0
        while i < len(p):
            c = p[i]
            if c == "*":
                if p[i:i + 3] == "**/":
                    out += "(?:.*/)?"; i += 3; continue
                if p[i:i + 2] == "**":
                    out += ".*"; i += 2; continue
                out += "[^/]*"
            elif c == "?":
                out += "[^/]"
            elif c == "{":
                j = p.find("}", i)
                if j == -1:
                    out += re.escape(c)
                else:
                    out += "(?:" + "|".join(translate(x) for x in p[i + 1:j].split(",")) + ")"; i = j
            else:
                out += re.escape(c)
            i += 1
        return out

    return re.fullmatch(translate(pattern), path) is not None


def rule_applies(rule: dict, path: str) -> bool:
    if not rule.get("enabled", True):
        return False
    langs = rule.get("languages") or []
    if langs and language_of(path) not in langs:
        return False
    pats = rule.get("file_patterns") or []
    return not pats or any(glob_match(p, path) for p in pats)


def render_file(diff: dict, max_chars: int) -> str:
    """Line-numbered rendering so the model can cite new-file lines: `L  12| +code`."""
    head = f"### FILE {diff['path']} ({diff['status']})"
    out, size = [head], len(head)
    for h in diff["hunks"]:
        for line in [h["header"]] + [
            (f"L{l['new_no']:>5}| {'+' if l['kind'] == 'add' else ' '}{l['text']}" if l["kind"] != "del" else f"      | -{l['text']}") for l in h["lines"]
        ]:
            line = redact_secrets(line)
            if size + len(line) + 1 > max_chars:
                out.append("[diff truncated: size limit]")
                return "\n".join(out)
            out.append(line)
            size += len(line) + 1
    return "\n".join(out)


def diff_text_index(diff: dict) -> str:
    """Whitespace-normalised, secret-redacted text of the diff, used to verify evidence quotes."""
    parts = [redact_secrets(l["text"]) for h in diff["hunks"] for l in h["lines"]]
    return " ".join(" ".join(parts).split())


@dataclass
class Batch:
    files: list[dict]
    texts: list[str]


def make_batches(diffs: list[dict], *, batch_chars: int, total_chars: int, max_batches: int) -> tuple[list[Batch], list[tuple[str, str]]]:
    """Greedy size-bounded batching. Returns (batches, [(path, reason)] for files left out by budget)."""
    batches: list[Batch] = []
    left_out: list[tuple[str, str]] = []
    cur = Batch([], [])
    cur_size = used = 0
    for d in diffs:
        text = render_file(d, batch_chars)
        if used + len(text) > total_chars:
            left_out.append((d["path"], "token_budget"))
            continue
        if cur.files and cur_size + len(text) > batch_chars:
            batches.append(cur)
            cur, cur_size = Batch([], []), 0
        if len(batches) >= max_batches:
            left_out.append((d["path"], "batch_limit"))
            continue
        cur.files.append(d); cur.texts.append(text)
        cur_size += len(text); used += len(text)
    if cur.files:
        if len(batches) < max_batches:
            batches.append(cur)
        else:
            left_out += [(f["path"], "batch_limit") for f in cur.files]
    return batches, left_out
