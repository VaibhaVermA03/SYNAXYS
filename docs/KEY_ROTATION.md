# Credential exposure and key rotation runbook

## A. Revoke a potentially exposed GitHub user authorization
The stored value is a GitHub **user** access token (stored Fernet-encrypted). Revoke it at the source:
1. The account owner: GitHub -> Settings -> Applications -> **Authorized GitHub Apps** (and **Authorized OAuth Apps**, check both) -> SYNAXYS -> **Revoke**.
   This invalidates the token immediately. Re-authorising later creates a new token.
2. Check GitHub -> Settings -> Security log for unexpected activity by that app.
3. If other people signed in to the exposed database, each of them must repeat step 1 for their own account (or the app owner revokes the grant via the GitHub API with the app's client id/secret).
4. Revoking does not uninstall the GitHub App from repositories and does not affect installation tokens (those are minted from the app's private key, which is not stored in the database).

## B. Rotate `ENCRYPTION_KEY` (encrypts stored GitHub tokens)
`ENCRYPTION_KEY` accepts several comma-separated Fernet keys: **the first encrypts, all decrypt**.
Replacing the key outright makes every stored token unreadable (users get "sign in with GitHub again"); the safe procedure is:
1. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
2. Set `ENCRYPTION_KEY=<NEW>,<OLD>` on **API and worker**, deploy both.
3. Re-encrypt: `python -m app.scripts.rotate_keys --dry-run`, then `python -m app.scripts.rotate_keys` (rewrites each stored token with the new key).
4. When it reports nothing left on the old key, set `ENCRYPTION_KEY=<NEW>` only and deploy.
Effect on sessions: none (sessions are random cookie values stored as SHA-256 hashes; they do not use this key).
If you simply replace the key and users must sign in again, the app now answers `github_reauth_required` (HTTP 409) instead of an internal error.

## C. Rotate `APP_SECRET_KEY`
Used to sign the OAuth state cookie and to derive CSRF tokens. Set the **same** new value on API and worker and redeploy.
* Existing sessions stay valid (they are database rows, not signed with this key).
* Open pages hold an old CSRF token: their next write is rejected once (403 `csrf_failed`) and the SPA refreshes it automatically.
* A sign-in that is in progress (up to 10 minutes) fails and has to be started again.
* Stored GitHub tokens are unaffected (different key).
To force everyone to sign in again, revoke all sessions: `UPDATE user_sessions SET revoked_at = now() WHERE revoked_at IS NULL;` (production database, after a backup).

## D. A database file or dump was shared
Sessions are stored only as hashes, so a leaked database cannot be used to forge cookies, and the token is useless without the key that encrypted it. Still: revoke (A), rotate the key that
encrypted it (B), and treat other contents (repository names, review text, audit log) as disclosed. Do not delete or edit the file until you have decided what you need from it
(a local development database is recreated by `alembic upgrade head` plus `python -m app.db.seed`; production uses PostgreSQL and is not affected).

## E. Keep it out of future archives and commits
Use the root `.gitignore`, run `python backend/tools/check_repo.py`, and build source archives with `python backend/tools/make_source_zip.py ../SYNAXYS_source.zip`
(it excludes databases, `.env` files, keys, caches and test output, and refuses to write the archive if it finds a credential).
Check Git: `git ls-files | grep -i sqlite`, `git log --all --full-history -- backend/synaxys_dev.sqlite3`, `git check-ignore -v backend/synaxys_dev.sqlite3`.
If the file was ever committed, removing it in a new commit is not enough: rewrite history (for example `git filter-repo --path backend/synaxys_dev.sqlite3 --invert-paths`), force-push, and assume it was already copied.
