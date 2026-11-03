"""Strict, dependency-free validation of GitHub webhook payloads and routing decisions.

Payloads are untrusted even after HMAC verification: every field used is type-checked
and length-bounded; errors carry only field names, never payload content.
"""
import re
from dataclasses import dataclass, field

SUPPORTED_PR_ACTIONS = {"opened", "synchronize", "reopened", "closed"}
_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")


class EventValidationError(ValueError):
    pass


def _get(d, path, typ, *, optional=False, maxlen=500):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            if optional:
                return None
            raise EventValidationError(f"missing field: {path}")
        cur = cur[k]
    if cur is None and optional:
        return None
    if typ is int and isinstance(cur, bool) or not isinstance(cur, typ):
        raise EventValidationError(f"invalid field: {path}")
    if isinstance(cur, str) and len(cur) > maxlen:
        raise EventValidationError(f"field too long: {path}")
    return cur


@dataclass(frozen=True)
class PullRequestEvent:
    action: str
    github_repo_id: int
    number: int
    title: str
    author: str
    state: str
    merged: bool
    base_branch: str
    head_branch: str
    head_sha: str
    html_url: str | None
    updated_at: str | None
    installation_id: int | None


def parse_pull_request(p: dict) -> PullRequestEvent:
    sha = _get(p, "pull_request.head.sha", str, maxlen=64)
    if not _SHA.match(sha):
        raise EventValidationError("invalid field: pull_request.head.sha")
    number = _get(p, "number", int)
    if number < 1:
        raise EventValidationError("invalid field: number")
    state = _get(p, "pull_request.state", str, maxlen=10)
    if state not in ("open", "closed"):
        raise EventValidationError("invalid field: pull_request.state")
    return PullRequestEvent(
        action=_get(p, "action", str, maxlen=40), github_repo_id=_get(p, "repository.id", int), number=number,
        title=_get(p, "pull_request.title", str), author=_get(p, "pull_request.user.login", str, maxlen=100),
        state=state, merged=bool(_get(p, "pull_request.merged", bool, optional=True)),
        base_branch=_get(p, "pull_request.base.ref", str, maxlen=200), head_branch=_get(p, "pull_request.head.ref", str, maxlen=200),
        head_sha=sha, html_url=_get(p, "pull_request.html_url", str, optional=True),
        updated_at=_get(p, "pull_request.updated_at", str, optional=True, maxlen=40),
        installation_id=_get(p, "installation.id", int, optional=True))


def decide_pr_action(ev: PullRequestEvent, repo_enabled: bool, allowed_actions: list[str]) -> str:
    """'review' | 'update_only' | 'ignore'"""
    if ev.action not in SUPPORTED_PR_ACTIONS:
        return "ignore"
    if ev.action == "closed" or ev.state != "open" or not repo_enabled:
        return "update_only"
    return "review" if ev.action in allowed_actions else "update_only"


@dataclass(frozen=True)
class PushEvent:
    ref: str
    after: str
    deleted: bool
    github_repo_id: int
    default_branch: str | None
    installation_id: int | None


def parse_push(p: dict) -> PushEvent:
    after = _get(p, "after", str, maxlen=64)
    return PushEvent(ref=_get(p, "ref", str, maxlen=300), after=after, deleted=bool(_get(p, "deleted", bool, optional=True)),
                     github_repo_id=_get(p, "repository.id", int), default_branch=_get(p, "repository.default_branch", str, optional=True, maxlen=200),
                     installation_id=_get(p, "installation.id", int, optional=True))


def push_targets_default_branch(ev: PushEvent) -> bool:
    return not ev.deleted and ev.default_branch is not None and ev.ref == f"refs/heads/{ev.default_branch}" \
        and bool(_SHA.match(ev.after)) and set(ev.after) != {"0"}


@dataclass(frozen=True)
class RepoRef:
    github_repo_id: int
    full_name: str
    private: bool


@dataclass(frozen=True)
class InstallationEvent:
    action: str
    installation_id: int
    account_login: str
    account_type: str
    added: list = field(default_factory=list)
    removed: list = field(default_factory=list)


def _repos(p, key):
    out = []
    for r in p.get(key) or []:
        if not isinstance(r, dict):
            raise EventValidationError(f"invalid field: {key}")
        out.append(RepoRef(_get(r, "id", int), _get(r, "full_name", str, maxlen=200), bool(r.get("private", False))))
    if len(out) > 1000:
        raise EventValidationError(f"too many entries: {key}")
    return out


def parse_installation(p: dict) -> InstallationEvent:
    return InstallationEvent(
        action=_get(p, "action", str, maxlen=40), installation_id=_get(p, "installation.id", int),
        account_login=_get(p, "installation.account.login", str, maxlen=100),
        account_type=_get(p, "installation.account.type", str, optional=True, maxlen=20) or "User",
        added=_repos(p, "repositories") if p.get("action") == "created" else _repos(p, "repositories_added"),
        removed=_repos(p, "repositories_removed"))
