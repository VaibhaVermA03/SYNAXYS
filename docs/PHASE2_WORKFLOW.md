# Phase 2: review workflow (search PR links, finding dismissal, queued-review cancel, GitHub comment deletion)

Status: implemented; only the stdlib-testable logic has been executed (see `IMPLEMENTATION_STATUS.md`, batch 14). Migration: `backend/migrations/versions/0004_review_workflow.py` (run `alembic upgrade head`).

## 1. Three separate states (never mixed)
| What | Column | Values |
|---|---|---|
| Finding | `review_findings.status` | `open`, `dismissed`, `published` |
| GitHub comment | `review_comments.state` | `draft`, `approved`, `publishing`, `published`, `failed`, `cancelled`, `deleted` |
| Review | `code_reviews.status` | `queued`, `processing`, `completed`, `failed`, `cancelled` |

## 2. Independent finding dismissal
* `POST /api/v1/reviews/{id}/findings/{finding_id}/dismiss` body `{"reason": "false_positive|not_applicable|will_fix_later|accepted_risk|other" (optional), "note": "<=300 chars" (optional, secrets rejected)}`; `POST .../restore`. Repository admins only, completed non-demo reviews, CSRF required, idempotent.
* No comment is needed and nothing is deleted. Stored on the finding: `dismissed_by_id`, `dismissed_at`, `dismiss_reason`, `dismiss_note`; audit actions `finding.dismiss` / `finding.restore`.
* Side effects: a pending comment (draft/approved/failed) is set to `cancelled` so it can never be published; a comment that is already `published` is not touched (delete it separately, section 4). Restore returns a comment to `draft` only if the dismissal itself cancelled it.
* Dismissed findings are excluded from severity counts, the dashboard and publishing; the review page shows "Show dismissed (N)" (`GET /reviews/{id}?include_dismissed=true`).
* **No reappearing findings:** when a review runs (also a re-run of the same review), earlier dismissals on the same pull request are loaded first. A new finding stays dismissed if its fingerprint is the same, or if it has the same file, category, title and identical evidence text (so it survives line numbers moving). Different code is a real new finding. Limit: if the evidence text itself changed, the finding is treated as new.
* The old comment-level "Dismiss" button is now called "Cancel comment" (it only cancels the comment; the finding stays active).

## 3. Cancel queued reviews
* `POST /api/v1/reviews/{id}/cancel` (repository admin or the person who requested the review). Buttons: review page and review list, only while `queued`.
* Real queue operation: `job_queue.cancel()` is an atomic `UPDATE ... WHERE status='queued'`; workers only claim `queued` rows, so a cancelled job is never picked up. The review row is changed in the same transaction and only `WHERE status='queued'`.
* Race with a worker: whoever updates first wins. If the worker claimed the job first, nothing changes and the API answers 409 `not_queued` ("picked up a moment ago"). `processing`, `completed`, `failed`, `cancelled` reviews are never cancellable (409 with a specific code).
* Recorded: `code_reviews.cancelled_by_id`, `cancelled_at`, `error="Cancelled by user"`, job `status=cancelled` + `last_error`, audit `review.cancel`. A cancelled review can be retried later (the existing retry endpoint; it clears the cancel fields, the audit entry stays).
* A queued review whose job is missing (orphan) is cancelled too (audit `orphaned: true`).

## 4. Delete published GitHub comments
* `DELETE /api/v1/reviews/{id}/comments/{comment_id}/github` (repository admin, rate limit 20/min, CSRF). UI: "Delete from GitHub" on a published comment, with a confirmation.
* Steps: comment must be `published` (never demo) -> fetch the comment from GitHub (id stored at publish time, or located by our hidden fingerprint marker when the id was not stored) -> verify it belongs to this repository and pull request, carries the marker for this finding, and (when `GITHUB_APP_SLUG` is set) was written by `<slug>[bot]` -> delete with the installation token -> **fetch again and require 404** -> only then `state='deleted'`, `github_deleted_at/by`, finding `published -> open`. The row is never removed.
* Outcomes: `deleted`; `already_deleted` (GitHub already returned 404, state reconciled); 409 `wrong_pull_request` / `not_our_comment` (nothing deleted); 502 `github_permission_denied` (the GitHub App needs **Pull requests: Read & write** and must be installed on the repository); 502 `delete_not_confirmed` (GitHub said OK but the comment still exists; state unchanged); 429 `github_rate_limited`. Every attempt is in `review_posting_attempts` (shown as "delete") and a success in the audit log (`comment.github_delete`).
* Not covered: the review summary body of the GitHub review is not a review comment and stays on GitHub.

## 5. Search -> pull request link
`POST /code-search/query` hits now carry `pull_request` (or null): a pull request of the same repository whose head commit IS the indexed commit, else whose head branch IS the searched branch (open before closed). The link is the `html_url` GitHub reported and we stored; it is accepted only if it is `https://github.com/<owner>/<repo>/pull/<n>`. Nothing is guessed from file paths or similarity. Today only default branches are indexed, so most hits have no PR; the branch selector and multi-branch indexing come in Phase 3 (including deleted/renamed branch handling). The results already show repository, branch and short commit.
