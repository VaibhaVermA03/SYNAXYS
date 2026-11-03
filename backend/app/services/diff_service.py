"""Unified-diff parsing and GitHub inline-comment line validation (stdlib only)."""
import re
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz",
                     ".woff", ".woff2", ".ttf", ".exe", ".bin", ".so", ".mp4", ".lock"}


@dataclass
class DiffLine:
    kind: str  # "add" | "del" | "context"
    old_no: int | None
    new_no: int | None
    text: str


@dataclass
class Hunk:
    header: str
    lines: list[DiffLine] = field(default_factory=list)

    def right_lines(self) -> set[int]:
        return {l.new_no for l in self.lines if l.new_no is not None}

    def left_lines(self) -> set[int]:
        return {l.old_no for l in self.lines if l.old_no is not None}


def is_probably_binary(path: str) -> bool:
    return any(path.lower().endswith(ext) for ext in BINARY_EXTENSIONS)


def parse_patch(patch: str | None) -> list[Hunk]:
    """Parse a GitHub per-file `patch`. Missing/truncated patches yield []."""
    if not patch:
        return []
    hunks: list[Hunk] = []
    cur: Hunk | None = None
    old_no = new_no = 0
    for raw in patch.split("\n"):
        m = _HUNK.match(raw)
        if m:
            cur = Hunk(header=raw)
            hunks.append(cur)
            old_no, new_no = int(m.group(1)), int(m.group(3))
            continue
        if cur is None or raw.startswith("\\"):  # "\ No newline at end of file"
            continue
        if raw.startswith("+"):
            cur.lines.append(DiffLine("add", None, new_no, raw[1:])); new_no += 1
        elif raw.startswith("-"):
            cur.lines.append(DiffLine("del", old_no, None, raw[1:])); old_no += 1
        else:
            cur.lines.append(DiffLine("context", old_no, new_no, raw[1:])); old_no += 1; new_no += 1
    return hunks


def validate_line_range(patch: str | None, start: int | None, end: int | None,
                        side: str = "RIGHT") -> bool:
    """True only if [start, end] lie in ONE hunk of the diff (GitHub requirement).

    Never relocates a finding; returns False so callers keep it summary-only.
    """
    if start is None or end is None or start < 1 or end < start:
        return False
    for h in parse_patch(patch):
        lines = h.right_lines() if side == "RIGHT" else h.left_lines()
        if all(n in lines for n in range(start, end + 1)):
            return True
    return False


def build_file_diff(f: dict, max_patch_bytes: int = 200_000) -> dict:
    """Normalise one GitHub PR file entry into the API shape. Never raises on odd input.

    Handles added/removed/renamed/modified, missing or truncated patches (GitHub omits `patch`
    for very large diffs), binary files and oversized patches (reported via skipped_reason).
    """
    path = str(f.get("filename", ""))
    patch = f.get("patch")
    skipped = None
    if is_probably_binary(path):
        skipped = "binary"
    elif patch is None:
        skipped = "no_content_change" if f.get("status") == "renamed" and not f.get("changes") else "patch_unavailable"
    elif len(patch.encode("utf-8", "ignore")) > max_patch_bytes:
        skipped = "too_large"
    hunks = [] if skipped else parse_patch(patch)
    return {
        "path": path, "previous_path": f.get("previous_filename"), "status": f.get("status", "modified"),
        "additions": int(f.get("additions", 0) or 0), "deletions": int(f.get("deletions", 0) or 0),
        "skipped_reason": skipped,
        "hunks": [{"header": h.header, "lines": [{"kind": l.kind, "old_no": l.old_no, "new_no": l.new_no, "text": l.text} for l in h.lines]} for h in hunks],
    }


def count_patch_changes(patch: str) -> tuple[int, int]:
    adds = dels = 0
    for h in parse_patch(patch):
        for l in h.lines:
            adds += l.kind == "add"
            dels += l.kind == "del"
    return adds, dels


def snippet_to_patch(code: str, max_lines: int = 200) -> tuple[str, int]:
    """Wrap a pasted snippet as an all-added single-hunk patch (used by the rule tester)."""
    lines = code.replace("\r\n", "\n").split("\n")[:max_lines]
    return f"@@ -0,0 +1,{len(lines)} @@\n" + "\n".join("+" + l for l in lines), len(lines)
