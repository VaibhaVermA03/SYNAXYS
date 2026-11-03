from datetime import datetime, timedelta, timezone
import copy
from app.services.webhook_events import (parse_pull_request, decide_pr_action, parse_push, push_targets_default_branch,
                                         parse_installation, EventValidationError)
from app.services.job_policy import backoff_seconds, is_stale, sanitize_error, is_retriable
from app.core.exceptions import NotConfigured, RateLimited
from app.services.github_http import GitHubAPIError

PR = {"action": "opened", "number": 7, "repository": {"id": 100}, "installation": {"id": 5},
      "pull_request": {"title": "T", "state": "open", "merged": False, "html_url": "http://x", "updated_at": "2026-01-01T00:00:00Z",
                       "user": {"login": "bob"}, "base": {"ref": "main"}, "head": {"ref": "f", "sha": "a" * 40}}}


def test_parse_pr_ok_and_rejects_bad_fields():
    ev = parse_pull_request(PR)
    assert (ev.number, ev.author, ev.head_sha, ev.installation_id) == (7, "bob", "a" * 40, 5)
    for mutate in (lambda p: p["pull_request"]["head"].update(sha="not-a-sha"), lambda p: p.update(number=0),
                   lambda p: p.update(number=True), lambda p: p["pull_request"].pop("user"),
                   lambda p: p["pull_request"].update(state="weird"), lambda p: p["pull_request"].update(title="x" * 501),
                   lambda p: p.update(repository={})):
        bad = copy.deepcopy(PR); mutate(bad)
        try: parse_pull_request(bad); assert False, "should reject"
        except EventValidationError as e: assert "x" * 50 not in str(e)   # no payload content in errors


def test_decide_pr_action():
    ev = parse_pull_request(PR); allowed = ["opened", "synchronize", "reopened"]
    assert decide_pr_action(ev, True, allowed) == "review"
    assert decide_pr_action(ev, False, allowed) == "update_only"          # repo not enabled
    assert decide_pr_action(ev, True, ["synchronize"]) == "update_only"    # action not allowed by config
    closed = parse_pull_request({**PR, "action": "closed", "pull_request": {**PR["pull_request"], "state": "closed", "merged": True}})
    assert decide_pr_action(closed, True, allowed) == "update_only" and closed.merged
    assert decide_pr_action(parse_pull_request({**PR, "action": "labeled"}), True, allowed) == "ignore"


def test_push_only_default_branch_non_delete():
    base = {"ref": "refs/heads/main", "after": "b" * 40, "repository": {"id": 1, "default_branch": "main"}}
    assert push_targets_default_branch(parse_push(base))
    assert not push_targets_default_branch(parse_push({**base, "ref": "refs/heads/dev"}))
    assert not push_targets_default_branch(parse_push({**base, "deleted": True}))
    assert not push_targets_default_branch(parse_push({**base, "after": "0" * 40}))


def test_parse_installation_created_and_repo_changes():
    p = {"action": "created", "installation": {"id": 9, "account": {"login": "org", "type": "Organization"}},
         "repositories": [{"id": 1, "full_name": "org/a", "private": True}]}
    ev = parse_installation(p)
    assert ev.account_type == "Organization" and ev.added[0].full_name == "org/a"
    p2 = {"action": "removed", "installation": {"id": 9, "account": {"login": "org"}}, "repositories_removed": [{"id": 1, "full_name": "org/a"}]}
    assert parse_installation(p2).removed[0].github_repo_id == 1
    try: parse_installation({"action": "created", "installation": {"id": 9, "account": {"login": "o"}}, "repositories": ["x"]}); assert False
    except EventValidationError: pass


def test_backoff_bounds_and_growth():
    lo = [backoff_seconds(a, rand=lambda: 0.0) for a in (1, 2, 3)]
    hi = [backoff_seconds(a, rand=lambda: 1.0) for a in (1, 2, 3)]
    assert lo == [7.5, 15.0, 30.0] and hi == [15.0, 30.0, 60.0]
    assert backoff_seconds(30, rand=lambda: 1.0) == 900.0               # capped


def test_is_stale_handles_naive_and_none():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert is_stale(datetime(2026, 1, 1, 11, 0), 600, now)                          # naive treated as UTC
    assert not is_stale(now - timedelta(seconds=100), 600, now)
    assert is_stale(None, 600, now)


def test_sanitize_error_redacts_and_truncates():
    out = sanitize_error(RuntimeError("boom ghp_" + "a" * 36 + "\n" + "x" * 900))
    assert "ghp_" not in out and len(out) <= 500 and "\n" not in out


def test_retriable_classification():
    assert is_retriable(RateLimited("x")) and is_retriable(GitHubAPIError(502)) and is_retriable(GitHubAPIError(0))
    assert not is_retriable(GitHubAPIError(404)) and not is_retriable(NotConfigured("x")) and is_retriable(RuntimeError("?"))
