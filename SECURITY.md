# Security

**Status:** security controls below are implemented in code and covered by tests, but most of those tests have **not been executed** (see [TESTING.md](TESTING.md)), no dependency audit has been run, and the system has never been exercised against real GitHub, OpenAI or Pinecone. This document does not claim the application is free of vulnerabilities. Have it reviewed and penetration-tested before processing real customer code.

## Assets and trust boundaries

| Asset | Where | Notes |
|---|---|---|
| GitHub user access tokens | `oauth_identities.access_token_enc` | Fernet-encrypted (`ENCRYPTION_KEY`), never returned to the browser, never logged |
| GitHub App private key, webhook secret, OpenAI/Pinecone keys, `APP_SECRET_KEY` | environment only | never in the database or frontend bundle; log output is redacted best-effort |
| Source code of connected repositories | GitHub → worker memory → OpenAI; indexed chunks in Pinecone | see *Data sent to third parties* |
| Review findings, draft comments, audit log | database | scoped by repository access |
| Sessions | `user_sessions` (SHA-256 of the cookie value) | 12 h default |

Untrusted inputs: everything in a pull request (code, diffs, titles, branch names), repository files used as retrieved context, webhook payloads (even after signature verification), custom review rules, all browser input. Trusted: server configuration and GitHub's REST responses for the authenticated installation.

## Threats and mitigations

| Threat | Mitigation (implementation) | Residual risk |
|---|---|---|
| Forged webhooks | HMAC-SHA256 over the **raw** body before parsing, constant-time compare (`core/security.py`, `api/v1/webhooks.py`); 401 on missing/invalid; endpoint disabled (503) without a secret | secret leakage = full forgery |
| Duplicate/replayed deliveries | unique `delivery_id`, unique review dedup keys, job `dedup_key`; failed deliveries may be redelivered | — |
| OAuth CSRF / code injection | signed, expiring `state` cookie + PKCE S256; callback redirects only to the configured frontend | PKCE honouring by GitHub for your app type is unverified |
| Session theft / fixation | HttpOnly, `Secure` (production), `SameSite=Lax` cookie; only a hash stored; new session per login; logout revokes | XSS or a malicious browser extension can still act as the user |
| CSRF on the API | per-session HMAC token in `X-CSRF-Token` for every unsafe method + `Origin` check against `CORS_ORIGINS` | — |
| Cross-tenant access | every query joins `repository_access`; "no access" and "does not exist" both return 404; vector queries use one namespace per repository and re-check `repo_id` in result metadata; frontend filters are never trusted | logic bugs; tests are unexecuted |
| Privilege escalation | connect/disconnect/index/approve/publish/policy require GitHub **admin** on the repository (role mapped from GitHub permissions at sync time) | role is refreshed only when the user runs *Sync from GitHub* |
| Prompt injection via repo content or rules | all repository-derived text, PR metadata, retrieved context and custom rules are wrapped as untrusted data with delimiter-spoof stripping; fixed system policy; the model has **no tools** and nothing is executed; output is schema- and evidence-validated (file in diff, quoted evidence present in that file, line inside one hunk); rules are validated and rejected if they look like policy overrides | cannot be fully eliminated: a model may still be misled into *wrong or missing findings*; findings are labelled AI suggestions and need human approval |
| Secret leakage to the LLM / vector DB | sensitive files (`.env`, keys, …) never sent or indexed; diff text redacted; chunks containing credential-looking text are not embedded (full-file detection incl. multi-line keys); evidence and comments are redacted | detection is pattern-based; unknown secret formats can slip through |
| Unintended posts to GitHub | drafts by default; admin approval; confirmation dialog; comment-only review (never approve/request changes); stale-commit and demo guards; fingerprint markers prevent duplicates; per-comment lock; audit trail | auto-publish (admin opt-in) removes the human gate |
| Credential exposure in errors/logs | error envelope hides internals; JSON logger redacts known secret patterns; provider errors are mapped without details | redaction is best-effort |
| Path traversal / SSRF through repo names | `valid_repo_name` rejects `.`/`..` segments; branch/sha inputs validated before URL building; only fixed GitHub hosts are contacted | — |
| Resource exhaustion | request size limit (2 MB default), per-IP rate limits, bounded review batches/files/findings, job timeouts and attempts, bounded pagination | rate limiter is **per process** |
| SQL injection | SQLAlchemy parameterised queries only; no raw SQL with user input | — |

## Required production settings

`APP_ENV=production` makes the application **refuse to start** unless: `APP_SECRET_KEY` is ≥ 32 characters and not the default; `ENCRYPTION_KEY` is set; `GITHUB_WEBHOOK_SECRET` is set; `COOKIE_SECURE=true`; `DATABASE_URL` is not SQLite; `REVIEW_USE_MOCK_LLM` is false; `VECTOR_BACKEND` is not `memory`. In production the OpenAPI docs are disabled and demo sign-in is ignored.

You should additionally: serve only over HTTPS; set `TRUST_PROXY_HEADERS=true` **only** when all traffic arrives through proxies you control; restrict `CORS_ORIGINS` to your frontend origin; give the GitHub App only the permissions in [docs/GITHUB_SETUP.md](docs/GITHUB_SETUP.md); store secrets in your host's secret manager; enable database backups.

## Secret generation and key rotation

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"                                # APP_SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"                                    # GITHUB_WEBHOOK_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # ENCRYPTION_KEY
```
GitHub App private key: download the `.pem` once, keep it outside the repository, and point `GITHUB_APP_PRIVATE_KEY_PATH` at it (or put it on one line with literal `\n` in `GITHUB_APP_PRIVATE_KEY`).

Rotating `ENCRYPTION_KEY`: (1) prepend the new key — `ENCRYPTION_KEY=<new>,<old>` — and restart API and worker; (2) run `python -m app.scripts.rotate_keys` (`--dry-run` first); (3) once it reports nothing left on the old key, remove it and restart. Tokens that cannot be decrypted with any key are reported; those users simply sign in again. Rotating `APP_SECRET_KEY` invalidates in-flight OAuth states and all CSRF tokens (users re-login). Rotating the webhook secret requires changing it in GitHub and the environment together.

## Data sent to third parties

* **OpenAI**: redacted diffs of reviewed files, PR title and branch names, enabled custom rules, retrieved context snippets, and the text of indexed chunks for embeddings. Check your OpenAI data-handling terms and your customers' consent first.
* **Pinecone**: for every indexed chunk, a vector plus metadata including up to 1,500 characters of source text, file path, line range, repository name and commit. Disconnecting a repository queues deletion of its namespace.
* **GitHub**: review comments you approve are posted by the GitHub App identity and cannot be removed from within SYNAXYS.

## Known limitations

* Rate limiting is in-memory per API process; with several replicas the effective limit multiplies. Use a single API instance or add a shared limiter / proxy limits.
* There is no account-deletion or data-export endpoint; review history and audit logs are kept until you delete database rows. Disconnecting removes vectors, not review history.
* GitHub user tokens from GitHub Apps expire (about 8 hours by default); sync then asks the user to sign in again. Repository roles are only refreshed on sync.
* Review quality is not measured; the evidence filter is deliberately conservative and may discard correct findings.
* LLM output is not a substitute for deterministic scanners (SAST, dependency, secret scanning); none are integrated and the product never claims that any ran.
* `render.yaml` and `frontend/vercel.json` were never applied; Alembic baseline `0001` creates tables from model metadata (later changes must be explicit migrations).
* No WAF, bot protection, MFA of its own (sign-in relies on GitHub), or per-tenant encryption keys.
* Dependency versions were pinned from memory and never audited.

## Reporting a vulnerability

Add your own security contact here before publishing (none is provided in this repository).
