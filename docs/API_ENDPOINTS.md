# API reference

_Generated from the route decorators by `backend/tools/gen_api_docs.py` — do not edit by hand._

Base path: `/api/v1`. Interactive OpenAPI docs are served at `/docs` when `APP_ENV` is not `production`.

| Method | Path | Success | Auth | Notes |
|---|---|---|---|---|
| GET | `/api/v1/auth/config` | 200 | Public |  |
| POST | `/api/v1/auth/demo-login` | 204 | Public (rate-limited) | Local demo only: signs in the seeded sample user. Disabled in production. |
| GET | `/api/v1/auth/github/callback` | 200 | Public (rate-limited) |  |
| GET | `/api/v1/auth/github/login` | 200 | Public (rate-limited) |  |
| POST | `/api/v1/auth/logout` | 204 | Public (session optional) |  |
| GET | `/api/v1/auth/me` | 200 | Session cookie |  |
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
| GET | `/api/v1/pull-requests` | 200 | Session cookie |  |
| GET | `/api/v1/pull-requests/{pull_request_id}` | 200 | Session cookie |  |
| GET | `/api/v1/pull-requests/{pull_request_id}/diff` | 200 | Session cookie |  |
| POST | `/api/v1/pull-requests/{pull_request_id}/review` | 202 | Session cookie + CSRF header |  |
| POST | `/api/v1/repositories/{repository_id}/index` | 202 | Session cookie + CSRF header |  |
| GET | `/api/v1/repositories/{repository_id}/index-status` | 200 | Session cookie |  |
| GET | `/api/v1/review-rules` | 200 | Session cookie |  |
| POST | `/api/v1/review-rules` | 201 | Session cookie + CSRF header |  |
| POST | `/api/v1/review-rules/test` | 200 | Session cookie + CSRF header | Runs ONE rule against a pasted snippet with the real engine. Nothing is stored or sent to GitHub. |
| DELETE | `/api/v1/review-rules/{rule_id}` | 204 | Session cookie + CSRF header |  |
| PATCH | `/api/v1/review-rules/{rule_id}` | 200 | Session cookie + CSRF header |  |
| GET | `/api/v1/reviews` | 200 | Session cookie |  |
| GET | `/api/v1/reviews/{review_id}` | 200 | Session cookie |  |
| POST | `/api/v1/reviews/{review_id}/approve` | 200 | Session cookie + CSRF header |  |
| PATCH | `/api/v1/reviews/{review_id}/comments/{comment_id}` | 200 | Session cookie + CSRF header |  |
| GET | `/api/v1/reviews/{review_id}/posting-attempts` | 200 | Session cookie |  |
| POST | `/api/v1/reviews/{review_id}/publish` | 200 | Session cookie + CSRF header |  |
| POST | `/api/v1/reviews/{review_id}/retry` | 202 | Session cookie + CSRF header |  |
| GET | `/api/v1/settings/audit` | 200 | Session cookie | The caller's OWN sensitive-operation history (never other users'). |
| GET | `/api/v1/settings/integrations` | 200 | Session cookie |  |
| POST | `/api/v1/webhooks/github` | 200 | HMAC signature (`X-Hub-Signature-256`) |  |

_39 endpoints._
