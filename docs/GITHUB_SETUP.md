# GitHub setup

SYNAXYS uses **one GitHub App** for both sign-in and repository access. (Registering a classic *OAuth App* is not enough: listing repositories relies on GitHub App *user-to-server* tokens.)

## Four different things — do not mix them up

| Layer | Question it answers | Where it is configured |
|---|---|---|
| **Identity (authentication)** | who is this person? | OAuth sign-in with the App's client ID/secret; produces a user token (stored encrypted) |
| **App installation** | which accounts/repositories did an owner let the App touch? | "Install App" on a user/org; you can choose *all* or *selected* repositories |
| **Repository permissions** | what may the App do there? | App settings: Contents read, Pull requests read/write, Metadata read — nothing else is requested |
| **Organisation policy** | may members install/approve Apps at all? | Org owners; installs by non-owners become *requests* that an owner must approve |

A user sees a repository in SYNAXYS only if they can access it **and** the App is installed on it. A user must be a GitHub **admin** of a repository to connect it, index it, approve/publish comments or change its policy.

## Create the App (GitHub → Settings → Developer settings → GitHub Apps → New)

| Field | Value |
|---|---|
| Homepage URL | your frontend URL (`http://localhost:5173` locally) |
| Callback URL | `GITHUB_REDIRECT_URI` — local: `http://localhost:8000/api/v1/auth/github/callback`; production: `https://YOUR-VERCEL-DOMAIN/api/v1/auth/github/callback` |
| Expire user authorization tokens | on (default; users sign in again after ~8 h when syncing) |
| Request user authorization (OAuth) during installation | optional |
| Webhook → Active | on |
| Webhook URL | local: your tunnel URL + `/api/v1/webhooks/github`; production: `https://YOUR-SERVICE.onrender.com/api/v1/webhooks/github` |
| Webhook secret | the value you put in `GITHUB_WEBHOOK_SECRET` |
| Repository permissions | **Contents: Read-only**, **Metadata: Read-only**, **Pull requests: Read and write** |
| Account permissions | none |
| Subscribe to events | **Pull request**, **Push** (`installation` and `installation_repositories` events are delivered to every App automatically) |
| Where can this App be installed? | "Only on this account" while testing |

After saving:
1. Copy **App ID** → `GITHUB_APP_ID`, the **slug** from the App's URL (`github.com/apps/<slug>`) → `GITHUB_APP_SLUG`.
2. **Client ID** → `GITHUB_CLIENT_ID`; *Generate a new client secret* → `GITHUB_CLIENT_SECRET`.
3. *Generate a private key* (downloads a `.pem`). Keep it **outside** the repository and set `GITHUB_APP_PRIVATE_KEY_PATH` to it — or put the PEM on one line with literal `\n` in `GITHUB_APP_PRIVATE_KEY`.
4. **Install** the App on your account/organisation and choose the repositories.
5. Restart the API and worker, open **Settings → Integrations** (all GitHub rows must be *Configured*), sign in, **Sync from GitHub**, then **Connect** a repository.

`pull_request` events are only turned into reviews for repositories that an admin has connected; the allowed events (opened / new commits / reopened) are configurable in **Settings → Integrations → Review policy**.

## Receiving webhooks locally

GitHub must reach your machine:

```bash
ngrok http 8000                    # or any tunnel; copy the https URL
```
Set the App's Webhook URL to `https://<tunnel>/api/v1/webhooks/github`. In the App's **Advanced** tab, *Recent deliveries* shows each delivery and lets you **Redeliver** (replays are safe: the same delivery id is not processed twice, unless the first attempt failed). Open a pull request on a connected repository; with the worker running, a review should appear within seconds. The tunnel URL changes on restart (free plans) — update the App when it does. Keep `GITHUB_REDIRECT_URI` on `localhost` (sign-in does not need the tunnel).

## Organisation notes

* Org owners can restrict third-party/GitHub App access; installation may need owner approval, and SAML SSO orgs may require authorising the App.
* Uninstalling the App (or removing a repository from it) is picked up through webhooks: reviewing is disabled and indexed data is queued for deletion.
* Review comments are posted by the App's bot identity and are visible to everyone who can see the pull request.

## Revoking

*Settings → Revoke stored GitHub credentials* deletes the encrypted user token (the App stays installed). To fully remove access, uninstall the App in GitHub.
