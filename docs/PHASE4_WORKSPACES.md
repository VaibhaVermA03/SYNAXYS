# Phase 4: workspaces, roles, invitations, notifications, account deletion and export

Status: implemented; only the stdlib-testable logic was executed (see `IMPLEMENTATION_STATUS.md`, batch 16). Migration `backend/migrations/versions/0006_workspaces.py` (`alembic upgrade head`; not downgradable: restore a backup). **Read "Upgrade" first.**

## Upgrade (existing data)
Existing access is converted **without widening it**: repositories whose set of (user, role) pairs in `repository_access` is identical share one workspace (single user: "<login>'s workspace", several users: "Shared workspace N"); every other user gets a personal workspace. The first `owner` of a group owns the workspace, other former owners become admins, former members stay members; a group with no owner makes its lowest user id the owner. After upgrading, open **Settings -> Workspaces** and review names/members. Users created later get a personal workspace at first sign-in.

## Model
* **Workspace** = tenant boundary. Roles: **owner** (exactly one: roles, ownership transfer, delete, invite policy), **admin** (connect/manage repositories, invite members, see workspace activity), **member** (view, request reviews).
* A repository belongs to at most one workspace (`repositories.workspace_id`); it is connected into a workspace by a workspace admin who is also GitHub-admin on that repository. A workspace can hold repositories of several GitHub installations (the repository points at its installation, not the workspace).
* **Access is derived:** for repositories in a workspace `repository_access` contains exactly one row per member (owner/admin -> repository role `owner`, member -> `member`) and nothing else; `workspace_service.sync_access` restores that invariant after every membership/repository change. GitHub sync no longer grants or revokes access to workspace repositories. Because every existing query already joins `repository_access`, reviews, findings, PRs, search and settings respect workspace boundaries without per-endpoint rewrites.
* **Pinecone:** namespaces stay `repo-<id>`; a repository has exactly one workspace and only that workspace's members have `repository_access`, so search can only reach vectors of repositories the caller is a member of (plus the existing `repo_id`/`branch` re-checks).
* **Active workspace:** the UI sends `X-Workspace-Id`; the backend verifies membership on every request (foreign/unknown id: 404) and uses it only to NARROW lists (repositories, pull requests, reviews, dashboard, search). It can never widen access.

## Endpoints (all `/api/v1`)
`/workspaces` (list, create) · `/workspaces/{id}` PATCH (name; invite policy: owner only) · `/workspaces/{id}/delete` (owner, type the name) · `/workspaces/{id}/members` (GET; PATCH `/{user_id}` role: owner only; DELETE) · `/workspaces/{id}/leave` · `/workspaces/{id}/transfer` · `/workspaces/{id}/invitations` (GET/POST; DELETE `/{id}`) · `/workspaces/invitations/mine|accept|{id}/decline` · `/workspaces/{id}/audit` (admin) · `/notifications` (+ `/unread-count`, `/read-all`, `/{id}/read`) · `/account/exports` (POST/GET, `/{id}/download`) · `/account/delete`. Connect: `POST /github/repositories/{id}/connect` takes an optional `workspace_id`.

## Invitations
Invite a **GitHub login** (no e-mail is stored). The API returns a one-time link token (stored only as a SHA-256 hash, valid 7 days); sharing it is up to the inviter. Accepting needs the token **and** a session of exactly that GitHub user (anybody else gets 404). One pending invitation per login; accepted/revoked/expired ones are kept for `RETENTION_INVITATIONS_DAYS`. Admins invite members, only the owner invites admins; ownership is never granted by invitation.

## Notifications
In-app, polled every 30 s (no extra infrastructure). Created for: review completed, findings generated, review failed, indexing finished/partial/failed, invitations, member joined/left/removed, role changes, ownership, export ready/failed. Recipients: the review's requester plus workspace owners/admins. `(user, dedup_key)` is unique, so retries and duplicate webhooks never notify twice. Links are restricted to internal `/app/...` paths. Retention: read notifications 90 days, any 365 days.

## Data export
`POST /account/exports` queues a job (one pending at a time, 3/hour) that builds a ZIP stored in `data_exports` (not on disk). Contents: profile, workspace memberships (member handles only where you are owner/admin), your review rules, activity, notifications, and review history/findings/comments of repositories you can access (max 5,000 rows per file, 40 MB). **Never** included: tokens, sessions, invitation tokens, other users' e-mail addresses. Download needs your own session (no shareable link); it expires after `EXPORT_TTL_HOURS` (24) and the cleanup job deletes it.

## Account deletion
`POST /account/delete` needs CSRF, the typed GitHub login, **and a session younger than 15 minutes** (sessions only come from a fresh GitHub sign-in; otherwise 403 "sign in again"). Then: workspaces where you are the only member are dissolved (repositories disconnected, vectors removed by the queue); shared workspaces survive and ownership goes to the longest-standing admin (else member); your memberships, repository access, review rules, notifications, exports, stored GitHub token and sessions are deleted; GitHub is asked to revoke the OAuth token (best effort); references in shared data (review requester, dismissals...) are cleared; the user row is deleted; the audit log keeps only an anonymous `account.deleted` event.

## Not covered (honest list)
* No e-mail/Slack delivery, no real-time push (polling only), no invitation e-mails (the inviter shares the link).
* A repository cannot be moved between workspaces (disconnect/dissolve and reconnect instead).
* Review rules created by a deleted user are deleted with them (other members lose those rules).
* Workspace audit shows workspace events plus repository- and review-level events; comment/finding-level events are not attributed to a workspace yet.
* No per-workspace billing/usage limits.
* The remote GitHub token revocation needs `GITHUB_CLIENT_ID/SECRET` and could not be tested.
