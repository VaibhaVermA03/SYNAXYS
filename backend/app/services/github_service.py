"""GitHub REST client: OAuth exchange, user-token calls, GitHub App JWT + installation tokens.

The HTTP library is injected (`http`) so tests use a fake; httpx is imported lazily.
Tokens are passed per call and never logged.
"""
import re
import time
from typing import TYPE_CHECKING, Any
from app.core.exceptions import NotConfigured
from app.services.github_http import GitHubAPIError, execute_with_retry, parse_next_link

if TYPE_CHECKING:
    from app.core.config import Settings

API = "https://api.github.com"
OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"


def _default_http():
    import httpx
    return httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False,
                        headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                                 "User-Agent": "synaxys"})


def _retry_exceptions() -> tuple:
    try:
        import httpx
        return (httpx.TransportError,)
    except ImportError:  # pragma: no cover
        return ()


_REPO_RE = re.compile(r"[\w.\-]+/[\w.\-]+")
_BRANCH_RE = re.compile(r"[\w./\-]+")
_SHA_RE = re.compile(r"[0-9a-fA-F]{7,64}")


def valid_repo_name(full_name: str) -> bool:
    """owner/name with safe characters; '.' and '..' segments are rejected (URL path traversal)."""
    return bool(_REPO_RE.fullmatch(full_name)) and not any(p in (".", "..") for p in full_name.split("/"))


class GitHubClient:
    def __init__(self, settings: "Settings", http=None):
        self.s = settings
        self._http = http or _default_http()
        self._inst_tokens: dict[int, tuple[str, float]] = {}

    # ---- low level -------------------------------------------------
    def _request(self, method: str, url: str, *, token: str | None = None, max_attempts: int = 4, **kw) -> Any:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if kw.pop("accept_json", False):
            headers["Accept"] = "application/json"
        res = execute_with_retry(lambda: self._http.request(method, url, headers=headers, **kw),
                                 max_attempts=max_attempts, retry_exceptions=_retry_exceptions())
        return res

    def get(self, path_or_url: str, token: str, **kw):
        url = path_or_url if path_or_url.startswith("http") else API + path_or_url
        return self._request("GET", url, token=token, **kw)

    def paginate(self, path: str, token: str, *, key: str | None = None, params: dict | None = None,
                 max_pages: int = 20) -> list:
        """Follow Link rel=next, bounded by max_pages. `key` extracts list from wrapper objects."""
        items: list = []
        url: str | None = API + path
        params = {"per_page": 100, **(params or {})}
        for _ in range(max_pages):
            if not url:
                break
            res = self._request("GET", url, token=token, params=params)
            params = None  # the `next` link already carries its query string
            items.extend(res.body[key] if key else res.body)
            url = parse_next_link({k.lower(): v for k, v in res.headers.items()}.get("link"))
        return items

    # ---- OAuth (user identity) --------------------------------------
    def exchange_code(self, code: str, code_verifier: str) -> dict:
        if not self.s.github_oauth_configured:
            raise NotConfigured("GitHub OAuth is not configured", code="github_oauth_not_configured")
        res = self._request("POST", OAUTH_TOKEN_URL, accept_json=True, data={
            "client_id": self.s.github_client_id, "client_secret": self.s.github_client_secret,
            "code": code, "redirect_uri": self.s.github_redirect_uri, "code_verifier": code_verifier})
        if not isinstance(res.body, dict) or "access_token" not in res.body:  # GitHub returns 200 + error body
            raise GitHubAPIError(400, "OAuth code exchange was rejected")
        return res.body

    def get_user(self, token: str) -> dict:
        return self.get("/user", token).body

    def list_user_installations(self, token: str) -> list[dict]:
        return self.paginate("/user/installations", token, key="installations")

    def list_user_installation_repos(self, token: str, installation_id: int) -> list[dict]:
        """Repos accessible to BOTH the user and the app installation (no over-listing)."""
        return self.paginate(f"/user/installations/{installation_id}/repositories", token, key="repositories")

    def list_pull_request_files(self, token: str, full_name: str, number: int, max_pages: int = 30) -> list[dict]:
        if not valid_repo_name(full_name):
            raise GitHubAPIError(400, "Invalid repository name")
        return self.paginate(f"/repos/{full_name}/pulls/{int(number)}/files", token, max_pages=max_pages)

    # ---- publishing (writes). POSTs are NOT auto-retried: a 5xx may have been applied, so the caller
    # re-checks for its fingerprint markers before trying again (see services.publish_service).
    @staticmethod
    def _repo(full_name: str) -> str:
        if not valid_repo_name(full_name):
            raise GitHubAPIError(400, "Invalid repository name")
        return full_name

    def list_pull_request_review_comments(self, token: str, full_name: str, number: int) -> list[dict]:
        return self.paginate(f"/repos/{self._repo(full_name)}/pulls/{int(number)}/comments", token, max_pages=30)

    def list_review_comments_of_review(self, token: str, full_name: str, number: int, review_id: int) -> list[dict]:
        return self.paginate(f"/repos/{self._repo(full_name)}/pulls/{int(number)}/reviews/{int(review_id)}/comments", token, max_pages=10)

    def create_pull_request_review(self, token: str, full_name: str, number: int, commit_id: str, body: str, comments: list[dict]) -> dict:
        """Event is hard-coded to COMMENT: never approves or requests changes."""
        res = self._request("POST", f"{API}/repos/{self._repo(full_name)}/pulls/{int(number)}/reviews", token=token, max_attempts=1,
                            json={"commit_id": commit_id, "body": body, "event": "COMMENT", "comments": comments})
        return res.body

    def create_review_comment(self, token: str, full_name: str, number: int, commit_id: str, comment: dict) -> dict:
        res = self._request("POST", f"{API}/repos/{self._repo(full_name)}/pulls/{int(number)}/comments", token=token, max_attempts=1,
                            json={**comment, "commit_id": commit_id})
        return res.body

    # ---- repository content (indexing)
    def get_branch_head(self, token: str, full_name: str, branch: str) -> str:
        if not _BRANCH_RE.fullmatch(branch) or ".." in branch:
            raise GitHubAPIError(400, "Invalid branch name")
        body = self.get(f"/repos/{self._repo(full_name)}/branches/{branch}", token).body
        return body["commit"]["sha"]

    def get_tree(self, token: str, full_name: str, commit_sha: str) -> dict:
        if not _SHA_RE.fullmatch(commit_sha):
            raise GitHubAPIError(400, "Invalid commit sha")
        return self.get(f"/repos/{self._repo(full_name)}/git/trees/{commit_sha}", token, params={"recursive": "1"}).body

    def get_blob(self, token: str, full_name: str, blob_sha: str, max_bytes: int = 1_000_000) -> bytes | None:
        """Raw bytes, or None when the blob is larger than max_bytes (never loaded into memory)."""
        import base64
        if not _SHA_RE.fullmatch(blob_sha):
            raise GitHubAPIError(400, "Invalid blob sha")
        body = self.get(f"/repos/{self._repo(full_name)}/git/blobs/{blob_sha}", token).body
        if int(body.get("size", 0)) > max_bytes:
            return None
        return base64.b64decode(body.get("content", "")) if body.get("encoding") == "base64" else str(body.get("content", "")).encode()

    # ---- GitHub App (installation auth) -----------------------------
    def app_jwt(self) -> str:
        if not self.s.github_app_configured:
            raise NotConfigured("GitHub App is not configured", code="github_app_not_configured")
        import jwt  # PyJWT
        key = self.s.github_app_private_key
        if not key and self.s.github_app_private_key_path:
            with open(self.s.github_app_private_key_path, encoding="utf-8") as fh:
                key = fh.read()
        now = int(time.time())
        return jwt.encode({"iat": now - 60, "exp": now + 9 * 60, "iss": self.s.github_app_id}, key.replace("\\n", "\n"), algorithm="RS256")

    def installation_token(self, installation_id: int) -> str:
        cached = self._inst_tokens.get(installation_id)
        if cached and cached[1] - 60 > time.time():
            return cached[0]
        res = self._request("POST", f"{API}/app/installations/{installation_id}/access_tokens", token=self.app_jwt())
        token = res.body["token"]
        self._inst_tokens[installation_id] = (token, time.time() + 3000)  # tokens live 1h; refresh early
        return token
