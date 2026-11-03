# Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `alembic: command not found` / `No module named app` | Activate the virtualenv and run commands from `backend/`. |
| PowerShell: *running scripts is disabled* when activating the venv | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again. |
| Worker logs *could not write heartbeat file* (Windows) | Set `WORKER_HEARTBEAT_PATH=worker.heartbeat` (default is a Linux `/tmp` path). Harmless otherwise. |
| `pip install` / `npm install` fails on a version | Pins were chosen from memory and never installed; loosen that one pin, run `pip check` / `npm ls`, commit the lockfile. |
| Backend exits at start in production with *Invalid production config* | The message lists exactly which guard failed (see SECURITY.md). |
| Login page says *GitHub sign-in is not configured* | Set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`, restart the API. |
| `invalid_state` after GitHub sign-in | The state cookie was lost: use `localhost` consistently (not `127.0.0.1`), allow cookies, finish within 10 minutes, make sure `GITHUB_REDIRECT_URI` equals the callback registered in GitHub **exactly**. In production it must be on the *frontend* domain. |
| Signed in but immediately signed out / endless login loop | Cookie not stored or not sent: production needs HTTPS + `COOKIE_SECURE=true`; the browser must talk to one origin (Vite proxy in dev, Vercel rewrite in prod). |
| `403 csrf_failed` from scripts | Send `X-CSRF-Token` from `/auth/me` with the session cookie; browsers do this automatically. |
| *Sign in with GitHub again* on Sync (`github_reauth_required`) | The stored user token expired or was revoked; sign out and in again. |
| No repositories after sync | The App is not installed on that account/repository, or you lack access. Use *Install GitHub App*, then sync again. |
| Connect/Index/Approve buttons disabled | You are not a GitHub **admin** of that repository. |
| Webhook delivery shows 401 | `GITHUB_WEBHOOK_SECRET` differs from the App's secret. 503 = secret not set. |
| Webhook accepted (202) but nothing happens | The **worker is not running** or cannot reach the same database. Check `python -m app.workers.runner` logs; jobs of unknown kinds fail with *No handler for job kind*. |
| Review stays *queued* with "Will retry: …" | A transient or configuration error; the note shows the sanitized cause. Permanent errors (e.g. OpenAI key rejected) turn it *failed* with a Retry button. |
| `openai_not_configured` / `pinecone_not_configured` (503) | Set the keys and restart both API and worker (see Settings → Integrations). |
| Indexing fails with *dimension … does not match* | `EMBEDDING_DIMENSIONS` ≠ Pinecone index dimension; recreate the index or fix the setting, then re-index. |
| Indexing fails: *tree_truncated* | Repository too large for GitHub's recursive tree API; not supported in this version. |
| Publish says *review_stale* | The PR received new commits; run a new review (line numbers would no longer match). |
| Some comments end *failed* after publishing | GitHub rejected that line position (422); other comments were posted individually. Edit/dismiss and re-review. |
| `github_permission_denied` on publish | Grant the App **Pull requests: Read & write**, then accept the new permission on the installation. |
| Search finds nothing | Repository not *indexed* yet, you lack access, or the language filter is too narrow. Demo/memory embeddings are lexical only. |
| Postgres `postgres://` URL rejected | It is normalised automatically; make sure the `psycopg` driver is installed (`requirements.txt`). |
| Headings look like a plain monospace font | The Geist Pixel Circle file is missing: run `npm run fonts:install` (needs internet), check `frontend/public/fonts/`, commit it. |
| Playwright cannot start the dev server | Run `npm run e2e:install` once; make sure port 5173 is free. |
