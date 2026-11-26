"""Phase 2 (batch 14), stdlib-only: dismissal carry-over matching, cancel rules, GitHub comment ownership checks, search -> PR link."""
from app.services.review_workflow_logic import (CANCEL_MESSAGES, build_dismissed_index, cancel_blocker, marker_fingerprints, match_dismissed, pick_related_pr,
                                                safe_github_pr_url, verify_comment_ownership)

FP = "abcdef0123456789abcdef0123456789"


def _f(**kw):
    return {"fingerprint": "aaa", "path": "a.py", "category": "security", "title": "SQL injection", "evidence": "query = f'select {x}'", **kw}


def test_dismissed_finding_is_recognised_by_fingerprint_or_by_same_code_after_lines_moved():
    idx = build_dismissed_index([_f()])
    assert match_dismissed(_f(), idx)                                                     # same fingerprint
    moved = _f(fingerprint="bbb", title="  sql   INJECTION ", evidence="query =  f'select {x}'")   # line numbers changed -> new fingerprint
    assert match_dismissed(moved, idx)
    assert not match_dismissed(_f(fingerprint="bbb", evidence="different code"), idx)     # different code: a real new finding
    assert not match_dismissed(_f(fingerprint="bbb", path="b.py"), idx)                   # other file
    assert not match_dismissed(_f(fingerprint="bbb", category="bug"), idx)
    assert match_dismissed(_f(), build_dismissed_index([])) is None


def test_cancel_is_only_allowed_while_waiting_in_the_queue():
    assert cancel_blocker(review_status="queued", is_demo=False) is None
    assert cancel_blocker(review_status="processing", is_demo=False) == "already_running"
    assert cancel_blocker(review_status="completed", is_demo=False) == "not_cancellable"     # may already be on GitHub
    assert cancel_blocker(review_status="failed", is_demo=False) == "not_cancellable"
    assert cancel_blocker(review_status="cancelled", is_demo=False) == "already_cancelled"
    assert cancel_blocker(review_status="queued", is_demo=True) == "demo_readonly"
    assert all(k in CANCEL_MESSAGES for k in ("already_running", "not_cancellable", "already_cancelled", "not_queued", "demo_readonly"))


def _gc(**kw):
    return {"id": 555, "pull_request_url": "https://api.github.com/repos/Alice/App/pulls/7", "body": f"text\n<!-- synaxys:fp={FP} -->", "user": {"login": "synaxys[bot]"}, **kw}


def test_comment_ownership_checks_repo_pr_marker_and_author():
    ok = dict(full_name="alice/app", number=7, fingerprint=FP, app_slug="synaxys")
    assert verify_comment_ownership(_gc(), **ok) is None                                          # repo name compare is case-insensitive
    assert verify_comment_ownership(_gc(), **{**ok, "number": 8}) == "wrong_pull_request"
    assert verify_comment_ownership(_gc(), **{**ok, "full_name": "alice/other"}) == "wrong_pull_request"
    assert verify_comment_ownership(_gc(pull_request_url="https://api.github.com/repos/alice/app/pulls/70"), **ok) == "wrong_pull_request"   # 7 vs 70
    assert verify_comment_ownership(_gc(pull_request_url=""), **ok) == "wrong_pull_request"
    assert verify_comment_ownership(_gc(), **{**ok, "fingerprint": "f" * 32}) == "not_our_comment"
    assert verify_comment_ownership(_gc(body="a human wrote this"), **ok) == "not_our_comment"    # never delete unrelated comments
    assert verify_comment_ownership(_gc(user={"login": "bob"}), **ok) == "not_our_comment"        # copied marker, different author
    assert verify_comment_ownership(_gc(user={"login": "bob"}), **{**ok, "app_slug": ""}) is None  # slug not configured: marker + PR + repo checks only
    assert verify_comment_ownership(_gc(user=None), **ok) == "not_our_comment"
    assert marker_fingerprints(None) == set() and marker_fingerprints(f"<!--synaxys:fp={FP}-->") == {FP}


def _pr(n, **kw):
    return {"id": n, "number": n, "title": f"PR {n}", "state": "open", "head_branch": f"feat-{n}", "head_sha": f"{n}" * 40, "updated": n, "html_url": f"https://github.com/alice/app/pull/{n}", **kw}


def test_search_hit_links_only_real_related_pull_requests():
    prs = [_pr(1), _pr(2), _pr(3, state="closed", head_branch="feat-2", updated=99)]
    assert pick_related_pr("feat-1", None, prs)["number"] == 1 and pick_related_pr("feat-1", None, prs)["match"] == "branch"
    assert pick_related_pr("feat-2", None, prs)["number"] == 2          # open PR wins over a newer closed one on the same branch
    assert pick_related_pr("main", "2" * 40, prs)["match"] == "commit"  # head commit IS the indexed commit
    assert pick_related_pr("main", "x" * 40, prs) is None               # default-branch hit with no matching PR: no link, nothing invented
    assert pick_related_pr(None, None, prs) is None
    assert pick_related_pr("feat-1", None, [_pr(1, html_url=None)]) is None                        # no stored URL -> no link (never fabricated)
    assert pick_related_pr("feat-1", None, [_pr(1, html_url="https://evil.example/alice/app/pull/1")]) is None


def test_pull_request_url_must_be_a_github_pull_url():
    assert safe_github_pr_url("https://github.com/alice/app/pull/12") == "https://github.com/alice/app/pull/12"
    for bad in (None, "", "http://github.com/a/b/pull/1", "https://github.com.evil.io/a/b/pull/1", "https://github.com/a/b/issues/1", "javascript:alert(1)", "https://github.com/a/b/pull/x"):
        assert safe_github_pr_url(bad) is None, bad
