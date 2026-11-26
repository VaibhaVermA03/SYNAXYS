# API reference

_Generated from the route decorators by `backend/tools/gen_api_docs.py` — do not edit by hand._

Base path: `/api/v1`. Interactive OpenAPI docs are served at `/docs` when `APP_ENV` is not `production`.

| Method | Path | Success | Auth | Notes |
|---|---|---|---|---|
| POST | `/api/v1/account/delete` | 204 | Session cookie + CSRF header | Irreversible. Requires: CSRF, the typed GitHub login, and a session younger than 15 minutes (sign in again if older). |
| GET | `/api/v1/account/exports` | 200 | Session cookie |  |
| POST | `/api/v1/account/exports` | 202 | Session cookie + CSRF header |  |
| GET | `/api/v1/account/exports/{export_id}/download` | 200 | Session cookie | Authenticated download (session cookie of the OWNER); there is no public or shareable link. |
| GET | `/api/v1/admin/jobs` | 200 | Session cookie | status defaults to 'failed'; pass an empty status for all. |
| GET | `/api/v1/admin/jobs/summary` | 200 | Session cookie |  |
| GET | `/api/v1/admin/jobs/{job_id}` | 200 | Session cookie |  |
| POST | `/api/v1/admin/jobs/{job_id}/retry` | 202 | Session cookie |  |
| GET | `/api/v1/auth/config` | 200 | Public |  |
| POST | `/api/v1/auth/demo-login` | 204 | Public (rate-limited) | Local demo only: signs in the seeded sample user. Disabled in production. |
| GET | `/api/v1/auth/github/callback` | 200 | Public (rate-limited) |  |
| GET | `/api/v1/auth/github/login` | 200 | Public (rate-limited) |  |
| POST | `/api/v1/auth/logout` | 204 | Public (session optional) |  |
| GET | `/api/v1/auth/me` | 200 | Session cookie |  |
| GET | `/api/v1/code-search/branches` | 200 | Session cookie | Branches the caller can search: indexed/partial branches of repositories they have access to (optionally one repository). |
| POST | `/api/v1/code-search/query` | 200 | Session cookie + CSRF header |  |
| GET | `/api/v1/dashboard` | 200 | Session cookie |  |
| DELETE | `/api/v1/github/credentials` | 204 | Session cookie + CSRF header | Deletes the stored (encrypted) GitHub user token. Re-login is required to sync again. |
| GET | `/api/v1/github/installations` | 200 | Session cookie |  |
| GET | `/api/v1/github/repositories` | 200 | Session cookie |  |
| POST | `/api/v1/github/repositories/sync` | 200 | Session cookie + CSRF header |  |
| GET | `/api/v1/github/repositories/{repository_id}/config` | 200 | Session cookie |  |
| PATCH | `/api/v1/github/repositories/{repository_id}/config` | 200 | Session cookie + CSRF header |  |
| POST | `/api/v1/github/repositories/{repository_id}/connect` | 200 | Session cookie + CSRF header |  |
| DELETE | `/api/v1/github/repositories/{repository_id}/disconnect` | 200 | Session cookie + CSRF header |  |
| GET | `/api/v1/health` | 200 | Public |  |
| GET | `/api/v1/health/ready` | 200 | Public |  |
| GET | `/api/v1/notifications` | 200 | Session cookie | The caller's own notifications only. With an active workspace: that workspace's plus workspace-independent ones (e.g. export ready). |
| POST | `/api/v1/notifications/read-all` | 200 | Session cookie + CSRF header |  |
| GET | `/api/v1/notifications/unread-count` | 200 | Session cookie |  |
| POST | `/api/v1/notifications/{notification_id}/read` | 204 | Session cookie + CSRF header |  |
| GET | `/api/v1/pull-requests` | 200 | Session cookie |  |
| GET | `/api/v1/pull-requests/{pull_request_id}` | 200 | Session cookie |  |
| GET | `/api/v1/pull-requests/{pull_request_id}/diff` | 200 | Session cookie |  |
| POST | `/api/v1/pull-requests/{pull_request_id}/review` | 202 | Session cookie + CSRF header |  |
| DELETE | `/api/v1/repositories/{repository_id}/branches/{branch:path}` | 202 | Session cookie + CSRF header | Remove ONE branch's index (vectors + state) through the queue. The default branch's index can be removed too (re-index to restore it). |
| GET | `/api/v1/repositories/{repository_id}/github-branches` | 200 | Session cookie | Live branch names from GitHub (installation token), so an admin can choose which extra branch to index. |
| POST | `/api/v1/repositories/{repository_id}/index` | 202 | Session cookie + CSRF header | Index (or incrementally refresh) one branch; no body = the default branch. Only changed files are processed. |
| GET | `/api/v1/repositories/{repository_id}/index-status` | 200 | Session cookie |  |
| POST | `/api/v1/repositories/{repository_id}/index/retry-failed` | 202 | Session cookie + CSRF header | Continue a PARTIAL index: failed batches become pending again and only the missing work is done (also continues after an exhausted embedding budget). |
| GET | `/api/v1/review-rules` | 200 | Session cookie |  |
| POST | `/api/v1/review-rules` | 201 | Session cookie + CSRF header |  |
| POST | `/api/v1/review-rules/test` | 200 | Session cookie + CSRF header | Runs ONE rule against a pasted snippet with the real engine. Nothing is stored or sent to GitHub. |
| DELETE | `/api/v1/review-rules/{rule_id}` | 204 | Session cookie + CSRF header |  |
| PATCH | `/api/v1/review-rules/{rule_id}` | 200 | Session cookie + CSRF header |  |
| GET | `/api/v1/reviews` | 200 | Session cookie |  |
| GET | `/api/v1/reviews/{review_id}` | 200 | Session cookie |  |
| POST | `/api/v1/reviews/{review_id}/approve` | 200 | Session cookie + CSRF header |  |
| POST | `/api/v1/reviews/{review_id}/cancel` | 200 | Session cookie + CSRF header | Cancel a review that is still waiting in the internal queue (not started, nothing on GitHub). |
| PATCH | `/api/v1/reviews/{review_id}/comments/{comment_id}` | 200 | Session cookie + CSRF header |  |
| DELETE | `/api/v1/reviews/{review_id}/comments/{comment_id}/github` | 200 | Session cookie + CSRF header | Delete a comment SYNAXYS published on GitHub. The internal record is kept (state 'deleted'); see services/comment_delete.py. |
| POST | `/api/v1/reviews/{review_id}/findings/{finding_id}/dismiss` | 200 | Session cookie + CSRF header | Dismiss ONE finding on its own: no comment needed, nothing deleted, who/when/why recorded. Idempotent. |
| POST | `/api/v1/reviews/{review_id}/findings/{finding_id}/restore` | 200 | Session cookie + CSRF header |  |
| GET | `/api/v1/reviews/{review_id}/posting-attempts` | 200 | Session cookie |  |
| POST | `/api/v1/reviews/{review_id}/publish` | 200 | Session cookie + CSRF header |  |
| POST | `/api/v1/reviews/{review_id}/retry` | 202 | Session cookie + CSRF header |  |
| GET | `/api/v1/settings/audit` | 200 | Session cookie | The caller's OWN sensitive-operation history (never other users'). |
| GET | `/api/v1/settings/integrations` | 200 | Session cookie |  |
| POST | `/api/v1/webhooks/github` | 200 | HMAC signature (`X-Hub-Signature-256`) |  |
| GET | `/api/v1/workspaces` | 200 | Session cookie |  |
| POST | `/api/v1/workspaces` | 201 | Session cookie + CSRF header |  |
| POST | `/api/v1/workspaces/invitations/accept` | 200 | Session cookie + CSRF header |  |
| GET | `/api/v1/workspaces/invitations/mine` | 200 | Session cookie |  |
| POST | `/api/v1/workspaces/invitations/{invitation_id}/decline` | 204 | Session cookie + CSRF header |  |
| PATCH | `/api/v1/workspaces/{workspace_id}` | 200 | Session cookie + CSRF header |  |
| GET | `/api/v1/workspaces/{workspace_id}/audit` | 200 | Session cookie |  |
| POST | `/api/v1/workspaces/{workspace_id}/delete` | 204 | Session cookie + CSRF header |  |
| GET | `/api/v1/workspaces/{workspace_id}/invitations` | 200 | Session cookie |  |
| POST | `/api/v1/workspaces/{workspace_id}/invitations` | 201 | Session cookie + CSRF header |  |
| DELETE | `/api/v1/workspaces/{workspace_id}/invitations/{invitation_id}` | 204 | Session cookie + CSRF header |  |
| POST | `/api/v1/workspaces/{workspace_id}/leave` | 204 | Session cookie + CSRF header |  |
| GET | `/api/v1/workspaces/{workspace_id}/members` | 200 | Session cookie |  |
| DELETE | `/api/v1/workspaces/{workspace_id}/members/{user_id}` | 204 | Session cookie + CSRF header |  |
| PATCH | `/api/v1/workspaces/{workspace_id}/members/{user_id}` | 204 | Session cookie + CSRF header |  |
| POST | `/api/v1/workspaces/{workspace_id}/transfer` | 204 | Session cookie + CSRF header |  |

_75 endpoints._
