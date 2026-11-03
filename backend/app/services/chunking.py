"""Deterministic, line-aware source chunking (heuristic 'language-aware': prefers cutting at top-level definitions)."""
import re
from dataclasses import dataclass

_BOUNDARY = {
    "python": r"(def |class |async def |@)", "javascript": r"(export |function |class |async function |module\.exports)",
    "typescript": r"(export |function |class |interface |type |async function )", "go": r"(func |type )", "ruby": r"(def |class |module )",
    "rust": r"(pub |fn |impl |struct |enum |mod )", "php": r"(function |class |abstract class |interface )", "java": r"(public |private |protected |class |interface |enum )",
    "csharp": r"(public |private |protected |internal |class |namespace )", "kotlin": r"(fun |class |object |interface )", "swift": r"(func |class |struct |enum |extension )",
    "sql": r"(CREATE |ALTER |create |alter )", "shell": r"(\w+\(\)\s*\{|function )", "c": r"[A-Za-z_][\w\s\*]*\(.*\)\s*\{?\s*$", "cpp": r"[A-Za-z_][\w\s\*:<>]*\(.*\)\s*\{?\s*$",
}


@dataclass(frozen=True)
class Chunk:
    start_line: int
    end_line: int
    text: str


def chunk_source(text: str, language: str | None = None, *, max_chars: int = 1500, overlap_lines: int = 2) -> list[Chunk]:
    boundary = re.compile(_BOUNDARY[language]) if language in _BOUNDARY else None
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    chunks: list[Chunk] = []
    cur: list[tuple[int, str]] = []
    size = 0

    def flush():
        nonlocal cur, size
        body = "\n".join(l for _, l in cur)
        if body.strip():
            chunks.append(Chunk(cur[0][0], cur[-1][0], body))
        cur, size = [], 0

    for no, line in enumerate(lines, 1):
        if len(line) > max_chars:  # pathological line (minified code): split by characters, same line number
            if cur:
                flush()
            for i in range(0, len(line), max_chars):
                piece = line[i:i + max_chars]
                if piece.strip():
                    chunks.append(Chunk(no, no, piece))
            continue
        starts_def = bool(boundary and boundary.match(line))
        if cur and (size + len(line) + 1 > max_chars or (starts_def and size >= max_chars * 0.4)):
            keep = [] if starts_def and size + len(line) + 1 <= max_chars else cur[-overlap_lines:] if overlap_lines and len(cur) > overlap_lines else []
            flush()
            cur, size = list(keep), sum(len(l) + 1 for _, l in keep)
        cur.append((no, line))
        size += len(line) + 1
    if cur:
        flush()
    return chunks
