"""Strict validation of user-supplied review rules (untrusted configuration)."""
import re

from app.agents.review_policies import detect_injection_markers
from app.core.exceptions import ValidationFailed

LANGUAGES = {"python", "javascript", "typescript", "java", "go", "rust", "ruby", "php", "c", "cpp", "csharp",
             "kotlin", "swift", "sql", "shell", "html", "css"}
_PATTERN = re.compile(r"^[A-Za-z0-9_\-./*?\[\]{}!,]+$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def validate_rule_fields(*, name=None, instruction=None, file_patterns=None, languages=None) -> dict:
    """Returns normalised values for the provided fields or raises ValidationFailed with per-field errors."""
    errors, out = [], {}

    def err(field, msg):
        errors.append({"loc": [field], "msg": msg})

    if name is not None:
        out["name"] = " ".join(name.split())
        if not out["name"]:
            err("name", "Name cannot be blank")
    if instruction is not None:
        text = instruction.strip()
        out["instruction"] = text
        if len(text) < 10:
            err("instruction", "Instruction must be at least 10 characters")
        if _CONTROL.search(text):
            err("instruction", "Instruction contains control characters")
        if re.search(r"(?i)</?\s*untrusted\s*>", text) or detect_injection_markers(text):
            err("instruction", "Instruction looks like an attempt to override system policy or prompt delimiters. "
                               "Rules may only describe what to look for in code.")
    if file_patterns is not None:
        pats = []
        for p in file_patterns:
            p = p.strip()
            if not p:
                continue
            if len(p) > 200 or not _PATTERN.match(p) or p.startswith("/") or ".." in p:
                err("file_patterns", f"Invalid file pattern: {p[:40]!r}")
            pats.append(p)
        out["file_patterns"] = list(dict.fromkeys(pats))
    if languages is not None:
        langs = [l.strip().lower() for l in languages if l.strip()]
        for l in langs:
            if l not in LANGUAGES:
                err("languages", f"Unsupported language: {l[:30]!r}")
        out["languages"] = list(dict.fromkeys(langs))
    if errors:
        raise ValidationFailed("Invalid rule", fields=errors)
    return out
