"""Minimal, dependency-free .gitignore matcher (pure). Supports comments, blank lines, negation (!), directory-only rules (trailing /),
anchored rules (leading / or a / in the middle), *, ?, [...] and ** (zero or more directories). Last matching rule wins; a path inside an
ignored directory stays ignored (git does not allow re-including files below an excluded directory)."""
import re


def _translate(pat: str) -> str:
    out, i, n = "", 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            if pat[i:i + 3] == "**/":
                out += "(?:.*/)?"
                i += 3
                continue
            if pat[i:i + 2] == "**":
                out += ".*"
                i += 2
                continue
            out += "[^/]*"
        elif c == "?":
            out += "[^/]"
        elif c == "[":
            j = pat.find("]", i + 2)
            if j == -1:
                out += re.escape(c)
            else:
                body = pat[i + 1:j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out += "[" + body.replace("\\", "\\\\") + "]"
                i = j
        elif c == "\\" and i + 1 < n:
            i += 1
            out += re.escape(pat[i])
        else:
            out += re.escape(c)
        i += 1
    return out


class GitIgnore:
    def __init__(self, text: str = "", *, max_rules: int = 2000):
        self.rules: list[tuple[re.Pattern, bool, bool]] = []  # (regex, negate, dir_only)
        for raw in (text or "").splitlines()[:max_rules]:
            line = raw.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            line = re.sub(r"(?<!\\)\s+$", "", line)
            negate = line.startswith("!")
            if negate:
                line = line[1:]
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            if not line:
                continue
            anchored = line.startswith("/") or "/" in line
            body = _translate(line.lstrip("/"))
            rx = ("^" if anchored else "^(?:.*/)?") + body + "$"
            try:
                self.rules.append((re.compile(rx), negate, dir_only))
            except re.error:
                continue  # an unparsable pattern is ignored, never fatal

    def _match(self, path: str, is_dir: bool) -> bool | None:
        verdict = None
        for rx, negate, dir_only in self.rules:
            if dir_only and not is_dir:
                continue
            if rx.match(path):
                verdict = not negate
        return verdict

    def ignored(self, path: str, *, is_dir: bool = False) -> bool:
        parts = path.strip("/").split("/")
        for k in range(1, len(parts)):  # any ignored ancestor directory ignores everything below it
            if self._match("/".join(parts[:k]), True):
                return True
        return bool(self._match("/".join(parts), is_dir))
