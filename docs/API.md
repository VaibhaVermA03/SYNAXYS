# API usage

Full endpoint table (generated from the code): [API_ENDPOINTS.md](API_ENDPOINTS.md). Interactive OpenAPI docs: `http://localhost:8000/docs` (disabled when `APP_ENV=production`).

## Authentication

Browser clients use the cookie session created by the GitHub OAuth flow (`GET /api/v1/auth/github/login` → GitHub → `/auth/github/callback` → redirect to the frontend). For developer/e2e scripts against a local backend started with `DEMO_LOGIN_ENABLED=true` and seeded data (no UI button exists; the endpoint is always disabled in production):

```bash
curl -c jar -X POST http://localhost:8000/api/v1/auth/demo-login          # needs `python -m app.db.seed`; dev only
curl -b jar http://localhost:8000/api/v1/auth/me                          # returns {"user":…, "csrf_token":"…"}
curl -b jar -H "X-CSRF-Token: <csrf_token>" -H "Content-Type: application/json" \
     -d '{"query":"where are webhooks verified"}' http://localhost:8000/api/v1/code-search/query
```

Every `POST`/`PATCH`/`DELETE` needs the cookie **and** `X-CSRF-Token`; if an `Origin` header is sent it must be in `CORS_ORIGINS`. There are no API keys or bearer tokens.

## Conventions

* Errors: `{"error": {"code": "...", "message": "..."}}`; validation errors (422) add `"fields": [{"loc": ["name"], "msg": "…"}]`. Stack traces and provider details are never returned.
* Status codes: 400 bad request / precondition, 401 not signed in, 403 forbidden (or CSRF), 404 not found **or no access**, 409 conflict (stale review, publish in progress, re-auth required), 413 body too large, 422 validation, 429 rate limited, 502 upstream (GitHub/OpenAI/Pinecone), 503 integration not configured (code names the missing piece, e.g. `pinecone_not_configured`).
* Pagination: `page` (≥1) and `page_size` (≤100) → `{items, total, page, page_size}`.
* Rate limits (per client IP, per process): auth login/callback/demo 10/min, code search 30/min, repository sync 6/min, indexing 6/min, manual review 20/min, publish 10/min, rule test 10/min (`*_RATE_LIMIT_PER_MINUTE` settings apply to auth and search).

## Webhook endpoint

`POST /api/v1/webhooks/github` expects GitHub's headers `X-GitHub-Event`, `X-GitHub-Delivery`, `X-Hub-Signature-256`. To test locally:

```python
import hashlib, hmac, json, urllib.request
secret, body = b"your-webhook-secret", json.dumps({"zen": "test"}).encode()
sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
req = urllib.request.Request("http://localhost:8000/api/v1/webhooks/github", data=body, method="POST",
      headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": "local-1", "X-Hub-Signature-256": sig, "Content-Type": "application/json"})
print(urllib.request.urlopen(req).read())        # {"status":"pong"}
```
A wrong signature returns 401; unsupported events are acknowledged and ignored; supported events are `pull_request` (opened, synchronize, reopened, closed), `push`, `installation`, `installation_repositories`.

## Health

`GET /api/v1/health` (liveness) and `GET /api/v1/health/ready` (database + which integrations are configured; never secrets).
