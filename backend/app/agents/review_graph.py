"""Bounded review workflow (deterministic pipeline, no unbounded agent loops):
select files -> redact+batch under size budgets -> model call per batch -> validate/dedup -> summary.
Pure of I/O except the injected `llm`; testable with a scripted fake."""
import time
from dataclasses import dataclass, field

from app.agents.prompts import build_messages
from app.agents.review_policies import detect_injection_markers
from app.services.diff_service import build_file_diff
from app.services.finding_validation import build_summary, validate_findings
from app.services.review_context import diff_text_index, exclusion_reason, make_batches, rule_applies


@dataclass
class Limits:
    batch_chars: int = 24_000
    total_chars: int = 120_000
    max_batches: int = 6
    max_files: int = 50
    max_patch_bytes: int = 200_000
    min_confidence: float = 0.5
    max_findings: int = 30


@dataclass
class ReviewInput:
    repo_id: int
    pr_number: int
    pr_title: str
    base_branch: str
    head_branch: str
    files: list[dict]
    rules: list[dict] = field(default_factory=list)
    context_snippets: list[dict] = field(default_factory=list)
    context_fn: object = None  # optional callable(eligible_diffs) -> list[dict]; supplies retrieved cross-file context


@dataclass
class ReviewResult:
    findings: list[dict]
    summary: str
    stats: dict
    model: str
    reviewed_files: list[str]
    skipped_files: list[tuple[str, str]]


class DeadlineExceeded(TimeoutError):
    pass


def run_review(inp: ReviewInput, llm, limits: Limits | None = None, *, deadline: float | None = None, clock=time.monotonic) -> ReviewResult:
    lim = limits or Limits()
    diffs = [build_file_diff(f, lim.max_patch_bytes) for f in inp.files[:lim.max_files]]
    skipped: list[tuple[str, str]] = [(f.get("filename", "?"), "file_limit") for f in inp.files[lim.max_files:]]
    eligible = []
    for d in diffs:
        reason = exclusion_reason(d)
        (skipped.append((d["path"], reason)) if reason else eligible.append(d))

    index = {d["path"]: {"patch": "\n".join(_raw_patch(f) for f in inp.files if f.get("filename") == d["path"]) or None, "text": diff_text_index(d)} for d in eligible}
    batches, left_out = make_batches(eligible, batch_chars=lim.batch_chars, total_chars=lim.total_chars, max_batches=lim.max_batches)
    skipped += left_out
    left = {p for p, _ in left_out}
    reviewed = [d["path"] for d in eligible if d["path"] not in left]
    index = {p: v for p, v in index.items() if p in reviewed}

    context = list(inp.context_snippets) or (list(inp.context_fn(eligible)) if inp.context_fn and eligible else [])
    raw: list = []
    injection_markers = 0
    for b in batches:
        if deadline is not None and clock() > deadline:
            raise DeadlineExceeded("Review exceeded its time budget")
        rules = [r for r in inp.rules if any(rule_applies(r, f["path"]) for f in b.files)]
        injection_markers += sum(len(detect_injection_markers(t)) for t in b.texts)
        out = llm.analyze(build_messages(pr_title=inp.pr_title, base_branch=inp.base_branch, head_branch=inp.head_branch, rules=rules,
                                         file_texts=b.texts, context_snippets=context))
        found = out.get("findings") if isinstance(out, dict) else None
        raw.extend(found if isinstance(found, list) else [])
    findings, stats = validate_findings(raw, index, repo_id=inp.repo_id, pr_number=inp.pr_number, min_confidence=lim.min_confidence, max_findings=lim.max_findings)
    stats.update(batches=len(batches), injection_markers_seen=injection_markers, context_snippets=len(context))
    model = getattr(llm, "model_name", "unknown-model")
    return ReviewResult(findings, build_summary(findings, stats, reviewed, skipped, model), stats, model, reviewed, skipped)


def _raw_patch(f: dict) -> str:
    return f.get("patch") or ""
