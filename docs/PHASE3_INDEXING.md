# Phase 3: scalable, branch-aware indexing

Status: implemented; only the stdlib-testable logic was executed (see `IMPLEMENTATION_STATUS.md`, batch 15). Migration: `backend/migrations/versions/0005_branch_indexing.py` (`alembic upgrade head`). **Read "Upgrade" before deploying.**

## Upgrade (existing indexes)
* Old index rows (`indexed_files`) are copied into `indexed_branch_files` with `branch = the repository's default branch` and `vector_schema = 1` (legacy vector ids without a branch tag); repositories that were `indexed` get a `branch_index_states` row, so **search keeps working** immediately.
* The first run after the upgrade re-embeds every legacy file under the new branch-aware ids and deletes the legacy vectors (so no duplicates remain). **That is a one-time re-embedding of the whole index (OpenAI cost).** Skip it for a repository by disconnecting/reconnecting only if you prefer a clean rebuild; there is no vector copy path.
* `0005` cannot be downgraded (restore a backup instead). The new settings are optional (defaults in `.env.example`).

## What changed
| Area | Before | Now |
|---|---|---|
| Branches | default branch only; vector ids = `<pathhash>#<n>` (would collide across branches) | per-branch state (`branch_index_states`), ids `<branchtag>:<pathhash>#<n>`, metadata `branch`; namespaces stay `repo-<id>` (the tenant boundary); extra branches limited by `INDEX_MAX_BRANCHES` (5) |
| Huge repositories | GitHub-truncated recursive tree = run refused | directory-by-directory listing (`INDEX_MAX_TREE_REQUESTS`); excluded directories (`node_modules`, build output, `.gitignore`'d, configured) are never even fetched; an **incomplete** listing never deletes anything |
| File limit | first N paths alphabetically (arbitrary) | ranked by value (source code, tests after production code, config, docs, other; shallow and small first) and cut at the limit; the rest is reported as `files_deferred` |
| Exclusions | built-in (binary, generated, vendored, secrets, size) | + repository root `.gitignore` (`INDEX_RESPECT_GITIGNORE`) + per-repository `index_include_globs`, `index_exclude_globs`, `index_max_files` (PATCH `/repositories/{id}/config`, admin) |
| Progress/retry | one all-or-nothing run | persisted batches (`INDEX_BATCH_FILES`, `INDEX_BATCH_BYTES`); a file-specific failure fails only its batch; **Continue** (`POST /repositories/{id}/index/retry-failed`) redoes only failed/pending work; provider outages retry the run without redoing finished batches |
| Time limits | run killed at the deadline, retried from the start | progress saved, the same job continues in a new queue job (`INDEX_MAX_CONTINUATIONS`) |
| Cost | none | per-run embedding budget `INDEX_MAX_CHUNKS_PER_RUN` (stops as `partial`, continue on request); unchanged blobs are never re-embedded; stale chunks are deleted by deterministic ids (no per-file list call) |
| Search | default branch implicit | branch selector; `GET /code-search/branches`; the branch filter is always applied and re-checked on every result |

## States
`branch_index_states.status`: `queued`, `indexing`, `indexed`, `partial` (searchable; some files/batches missing), `failed`, `missing` (GitHub has no such branch; excluded from search, **nothing deleted automatically**). `Repository.index_status` keeps mirroring the default branch.

## Endpoints (admin = repository admin)
`POST /repositories/{id}/index` body `{"branch": "..."}` (optional; verified on GitHub; double clicks reuse the running job) · `GET /repositories/{id}/index-status?branch=` (branches list, batch counts, plan summary) · `GET /repositories/{id}/github-branches` · `POST /repositories/{id}/index/retry-failed` · `DELETE /repositories/{id}/branches/{branch}` (queue job `index_branch_delete`) · `GET /code-search/branches`.
Webhooks: a push to an **indexed** branch refreshes it incrementally; a push event that deletes an indexed branch queues cleanup of only that branch; other branches/tags are ignored.

## Safety properties
* Isolation: one Pinecone namespace per repository; the API only queries repositories reachable through `repository_access`; every result is re-checked for `repo_id` and `branch`.
* Branch names are validated (`[\w./-]`, no `..`) and never used as file paths; vector ids use a hash of the branch.
* Only one writer per branch: a second run while one is active is retried later by the queue.
* Secret-looking chunks are dropped before embedding (unchanged); code text up to 1,500 characters per chunk is stored in Pinecone metadata (see the privacy notes in `SECURITY.md`).

## Not covered (honest list)
* Identical files on several branches are embedded once per branch (no vector sharing).
* Only the repository's **root** `.gitignore` is read (nested ones are not).
* If a run crashes between the Pinecone upsert and the database commit, a file that shrank may keep orphan chunks until its next change (ids are deterministic, so they are overwritten or deleted then).
* Renamed default branches: the old branch's state is not migrated automatically; index the new default branch (and remove the old one).
* A repository whose single directory has more than 100,000 entries is listed incompletely (reported as `tree_incomplete`).
* No UI to edit the per-repository include/exclude globs yet (API only).
