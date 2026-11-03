"""Demo seed. Everything created here has is_demo=True and is labelled as sample data.

Usage: python -m app.db.seed   (after `alembic upgrade head`)
Demo data is NOT real GitHub activity; publishing demo reviews is refused by the API.
"""
from sqlalchemy import select

from app.core.security import finding_fingerprint
from app.db.session import SessionLocal
from app.models import (CodeReview, GitHubInstallation, PullRequest, Repository, RepositoryAccess,
                        ReviewComment, ReviewConfiguration, ReviewFinding, ReviewRule, User)

DEMO_PATCH = """@@ -10,6 +10,9 @@ def get_user(db, name):
     cursor = db.cursor()
-    cursor.execute("SELECT * FROM users WHERE name = %s", (name,))
+    query = "SELECT * FROM users WHERE name = '" + name + "'"
+    cursor.execute(query)
+    # TODO: cache
     return cursor.fetchone()"""


def seed(login: str = "demo-user", github_id: int = -1) -> None:
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.github_id == github_id)):
            print("Demo data already present."); return
        user = User(github_id=github_id, login=login, name="Demo User")
        db.add(user); db.flush()
        inst = GitHubInstallation(installation_id=-1, account_login=login, owner_user_id=user.id, is_demo=True)
        db.add(inst); db.flush()
        repo = Repository(installation_id=inst.id, github_repo_id=-1, full_name="demo/sample-api", default_branch="main",
                          language="Python", is_enabled=True, is_demo=True, html_url=None)
        repo.config = ReviewConfiguration()
        db.add(repo); db.flush()
        db.add(RepositoryAccess(user_id=user.id, repository_id=repo.id, role="owner"))
        pr = PullRequest(repository_id=repo.id, number=1, title="[DEMO] Add user lookup by name", author_login="demo-dev",
                         state="open", base_branch="main", head_branch="feature/lookup", head_sha="demo000sha",
                         is_demo=True, demo_patches={"app/users.py": DEMO_PATCH})
        db.add(pr); db.flush()
        rev = CodeReview(pull_request_id=pr.id, dedup_key="demo:pr1", head_sha="demo000sha", status="completed",
                         trigger="demo", model="demo-fixture (no LLM was called)", is_demo=True,
                         summary="SAMPLE DATA: fixture review, not produced by an AI model.")
        db.add(rev); db.flush()
        fp = finding_fingerprint(repo.id, 1, "app/users.py", 11, 12, "security", "SQL injection via string concatenation")
        f = ReviewFinding(review_id=rev.id, fingerprint=fp, category="security", severity="high", confidence=0.9,
                          title="SQL injection via string concatenation", path="app/users.py", start_line=11, end_line=12,
                          explanation="User-controlled `name` is concatenated into the SQL string (AI suggestion, unverified).",
                          evidence="query = \"SELECT * FROM users WHERE name = '\" + name + \"'\"",
                          remediation="Use a parameterized query: cursor.execute(sql, (name,)).", inline_possible=True)
        f.comment = ReviewComment(body="[Demo] Possible SQL injection: use parameterized queries.")
        db.add(f)
        db.add(ReviewRule(owner_user_id=user.id, name="Unsafe SQL construction", is_demo=True,
                          instruction="Flag SQL built via string concatenation or f-strings.", severity="high",
                          file_patterns=["**/*.py"], languages=["python"]))
        db.add(ReviewRule(owner_user_id=user.id, name="Validate external input", is_demo=True,
                          instruction="Flag request data used without validation.", severity="medium"))
        db.commit()
        print("Seeded demo data (labelled is_demo=True).")


if __name__ == "__main__":
    seed()
