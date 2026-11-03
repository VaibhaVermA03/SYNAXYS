from app.services.publish_logic import (EVENT, MAX_BODY, can_transition, existing_markers, inline_payload, marker, plan, publish_blocker, with_marker)

FP = "ab12cd34ef56ab12cd34ef56ab12cd34"


def test_marker_roundtrip_and_cap():
    body = with_marker("Hello\n\n", FP)
    assert body.endswith(marker(FP)) and existing_markers([{"body": body}, {"body": "no marker"}, {"body": None}, {}]) == {FP}
    assert len(with_marker("x" * 100_000, FP)) <= MAX_BODY
    assert existing_markers([{"body": "<!--synaxys:fp=" + FP + "-->"}]) == {FP}            # tolerant of spacing
    assert existing_markers([{"body": "<!-- synaxys:fp=NOT-HEX -->"}]) == set()


def test_inline_payload_single_and_multi_line_right_side_only():
    assert inline_payload("a.py", 5, 5, "b") == {"path": "a.py", "line": 5, "side": "RIGHT", "body": "b"}
    m = inline_payload("a.py", 3, 6, "b")
    assert m["line"] == 6 and m["start_line"] == 3 and m["start_side"] == "RIGHT" and m["side"] == "RIGHT"


def test_plan_skips_existing_and_in_batch_duplicates():
    items = [{"fingerprint": "a" * 16, "id": 1}, {"fingerprint": "b" * 16, "id": 2}, {"fingerprint": "b" * 16, "id": 3}]
    post, dup = plan(items, {"a" * 16})
    assert [i["id"] for i in post] == [2] and [i["id"] for i in dup] == [1, 3]


def test_event_is_comment_never_approval():
    assert EVENT == "COMMENT"


def _b(**o):
    base = dict(review_status="completed", is_demo=False, repo_enabled=True, pr_state="open", pr_head="a", review_head="a", app_configured=True)
    return publish_blocker(**{**base, **o})


def test_publish_blockers_in_priority_order():
    assert _b() is None
    assert _b(is_demo=True, review_status="failed") == "demo_readonly"
    assert _b(review_status="queued") == "review_not_completed"
    assert _b(repo_enabled=False) == "repository_not_connected"
    assert _b(pr_state="closed") == "pr_not_open"
    assert _b(pr_head="b") == "review_stale"
    assert _b(app_configured=False) == "github_app_not_configured"


def test_comment_state_transitions():
    assert can_transition("draft", "cancelled") and can_transition("approved", "draft") and can_transition("cancelled", "draft") and can_transition("failed", "draft")
    assert not can_transition("published", "draft") and not can_transition("publishing", "cancelled") and not can_transition("draft", "approved")   # approval only via approve endpoint
