"""Platform-administrator allow-list parsing. Pure (no third-party imports).

Admins are identified ONLY by numeric GitHub user IDs configured in ADMIN_GITHUB_IDS; there is no database flag
and no way to become an admin through the application. Negative IDs (the seeded demo user) are never admins.
"""


def parse_admin_ids(raw: str | None) -> frozenset[int]:
    ids: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isascii() or not part.isdigit() or int(part) <= 0:
            raise ValueError("ADMIN_GITHUB_IDS must be a comma-separated list of positive numeric GitHub user IDs (not logins)")
        ids.add(int(part))
    return frozenset(ids)


def is_admin_github_id(github_id: int | None, admin_ids: frozenset[int]) -> bool:
    return github_id is not None and github_id > 0 and github_id in admin_ids
