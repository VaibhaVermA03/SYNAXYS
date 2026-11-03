"""Turns raw (untrusted) model output into persisted-quality findings.

Guarantees: closed enums; bounded, secret-redacted text; the file must be in the reviewed diff;
the evidence quote must appear in that file's diff; line ranges are kept ONLY if valid for one
hunk (never relocated); low-confidence and duplicate findings are dropped; counts are reported.
"""
import re

from app.core.security import finding_fingerprint, redact_secrets
from app.services.diff_service import validate_line_range

CATEGORIES = {"bug", "security", "performance", "maintainability", "testing"}
SEVERITIES = {"critical", "high", "medium", "low", "info"}
_ALIASES = {"bugs": "bug", "correctness": "bug", "logic": "bug", "style": "maintainability", "quality": "maintainability",
            "perf": "performance", "tests": "testing", "test": "testing", "vulnerability": "security"}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EVIDENCE_PREFIX = re.compile(r"^\s*L\s*\d+\s*\|\s?[+\- ]?")
LIMITS = {"title": 200, "explanation": 2000, "evidence": 1000, "remediation": 1500, "patch": 3000}


def clean(text, limit: int) -> str:
    return redact_secrets(_CONTROL.sub("", str(text or ""))).strip()[:limit]


def _int(v):
    if isinstance(v, bool):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


def evidence_supported(evidence: str, file_text: str) -> bool:
    """At least one meaningful evidence line must literally occur in the (redacted) diff text of that file."""
    for raw in evidence.splitlines():
        line = " ".join(_EVIDENCE_PREFIX.sub("", raw).split())
        if len(line) >= 6 and line in file_text:
            return True
    return False


def _tokens(title: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", title.lower()))


def _similar(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.6


def validate_findings(raw: list, index: dict[str, dict], *, repo_id: int, pr_number: int, min_confidence: float = 0.5,
                      max_findings: int = 30) -> tuple[list[dict], dict]:
    """index: path -> {"patch": str|None, "text": normalised redacted diff text}."""
    stats = {"candidates": len(raw or []), "invalid_schema": 0, "unknown_file": 0, "no_evidence": 0, "low_confidence": 0,
             "duplicates": 0, "lines_unverified": 0, "over_limit": 0}
    accepted: list[dict] = []
    for r in raw or []:
        if not isinstance(r, dict):
            stats["invalid_schema"] += 1
            continue
        category = _ALIASES.get(str(r.get("category", "")).strip().lower(), str(r.get("category", "")).strip().lower())
        severity = str(r.get("severity", "")).strip().lower()
        title, explanation = clean(r.get("title"), LIMITS["title"]), clean(r.get("explanation"), LIMITS["explanation"])
        try:
            confidence = float(r.get("confidence"))
        except (TypeError, ValueError):
            confidence = None
        if category not in CATEGORIES or severity not in SEVERITIES or not title or not explanation or confidence is None or confidence != confidence:
            stats["invalid_schema"] += 1
            continue
        confidence = min(1.0, max(0.0, confidence))
        path = str(r.get("path", "")).strip()
        entry = index.get(path)
        if entry is None:
            stats["unknown_file"] += 1
            continue
        evidence_raw = redact_secrets(str(r.get("evidence") or ""))  # the diff index is redacted too
        if not evidence_supported(evidence_raw, entry["text"]):
            stats["no_evidence"] += 1
            continue
        if confidence < min_confidence:
            stats["low_confidence"] += 1
            continue
        start, end = _int(r.get("start_line")), _int(r.get("end_line"))
        if start is not None and end is None:
            end = start
        inline = validate_line_range(entry["patch"], start, end)
        if not inline:
            if start is not None or end is not None:
                stats["lines_unverified"] += 1
            start = end = None  # explicit "no verified location" — never relocate to another line
        f = {"category": category, "severity": severity, "title": title, "explanation": explanation, "evidence": clean(evidence_raw, LIMITS["evidence"]),
             "path": path, "start_line": start, "end_line": end, "remediation": clean(r.get("remediation"), LIMITS["remediation"]) or None,
             "patch": clean(r.get("patch"), LIMITS["patch"]) or None, "confidence": round(confidence, 2), "inline_possible": inline}
        f["fingerprint"] = finding_fingerprint(repo_id, pr_number, path, start, end, category, title)
        dup = next((a for a in accepted if a["fingerprint"] == f["fingerprint"] or
                    (a["path"] == path and a["category"] == category and start is not None and a["start_line"] == start and _similar(a["title"], title))), None)
        if dup is not None:
            stats["duplicates"] += 1
            if f["confidence"] > dup["confidence"]:
                accepted[accepted.index(dup)] = f
            continue
        accepted.append(f)
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    accepted.sort(key=lambda x: (order[x["severity"]], -x["confidence"], x["path"], x["start_line"] or 0))
    if len(accepted) > max_findings:
        stats["over_limit"] = len(accepted) - max_findings
        accepted = accepted[:max_findings]
    stats["accepted"] = len(accepted)
    return accepted, stats


def build_summary(findings: list[dict], stats: dict, reviewed: list[str], skipped: list[tuple[str, str]], model: str) -> str:
    sev = {}
    for f in findings:
        sev[f["severity"]] = sev.get(f["severity"], 0) + 1
    lines = [f"AI-assisted review by {model}: {len(reviewed)} file(s) reviewed"
             + (f", {len(skipped)} not reviewed ({', '.join(sorted({r for _, r in skipped}))})." if skipped else ".")]
    if findings:
        lines.append(f"{len(findings)} suggestion(s): " + ", ".join(f"{n} {s}" for s, n in sorted(sev.items(), key=lambda kv: ["critical", "high", "medium", "low", "info"].index(kv[0]))) + ".")
        unplaced = [f for f in findings if not f["inline_possible"]]
        if unplaced:
            lines.append(f"{len(unplaced)} could not be attached to a valid diff line and are listed here only: "
                         + "; ".join(f"[{f['severity']}] {f['path']}: {f['title']}" for f in unplaced[:10]) + ".")
    else:
        lines.append("No actionable issues were found in the reviewed changes. This is not a guarantee that the code is free of defects or vulnerabilities.")
    dropped = sum(stats.get(k, 0) for k in ("invalid_schema", "unknown_file", "no_evidence", "low_confidence"))
    if dropped:
        lines.append(f"{dropped} candidate finding(s) were discarded as unsupported (missing evidence, unknown file, or low confidence).")
    return " ".join(lines)
