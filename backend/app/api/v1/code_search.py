"""Semantic code search. Tenant isolation is enforced HERE (server side): only repositories the caller can
access through RepositoryAccess are ever queried, each in its own namespace; browser filters are never trusted."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import active_workspace, current_user, rate_limit, settings_dep
from app.core.config import Settings
from app.core.exceptions import NotConfigured
from app.db.session import get_db
from app.models import BranchIndexState, PullRequest, Repository, RepositoryAccess, User
from app.repositories.access import get_repo_for_user
from app.schemas.search import PullRequestRef, SearchBranchesOut, SearchBranchOut, SearchHit, SearchIn, SearchOut
from app.services.embedding_service import check_dimensions, get_embedder
from app.services.index_policy import namespace_for
from app.services.review_workflow_logic import pick_related_pr
from app.services.search_logic import build_filter, explain_match, github_blob_url, merge_results
from app.services.vector_service import get_vector_store, indexing_available

router = APIRouter(prefix="/code-search", tags=["code-search"])
limit_search = rate_limit("code_search", "search_rate_limit_per_minute")
MAX_REPOS = 20
REASONS = {"pinecone_not_configured": "Pinecone is not configured. Set PINECONE_API_KEY and PINECONE_INDEX_NAME.",
           "openai_not_configured": "OpenAI is not configured. Set OPENAI_API_KEY to enable embeddings."}


def _related_prs(db: Session, merged: list[dict]) -> dict[int, list[dict]]:
    """One query for all hits: the pull requests (of repositories the caller can already search) that could be related to them."""
    repo_ids = {m["repo"]["id"] for m in merged}
    branches = {m["metadata"].get("branch") for m in merged if m["metadata"].get("branch")}
    commits = {m["metadata"].get("commit") for m in merged if m["metadata"].get("commit")}
    if not repo_ids or not (branches or commits):
        return {}
    rows = db.scalars(select(PullRequest).where(PullRequest.repository_id.in_(repo_ids), PullRequest.is_demo.is_(False), PullRequest.html_url.is_not(None),
                                                or_(PullRequest.head_branch.in_(branches or {""}), PullRequest.head_sha.in_(commits or {""})))).all()
    out: dict[int, list[dict]] = {}
    for p in rows:
        out.setdefault(p.repository_id, []).append({"id": p.id, "number": p.number, "title": p.title, "state": "merged" if p.merged else p.state, "head_branch": p.head_branch,
                                                    "head_sha": p.head_sha, "html_url": p.html_url, "updated": (p.github_updated_at or p.updated_at).timestamp() if (p.github_updated_at or p.updated_at) else 0})
    return out


@router.get("/branches", response_model=SearchBranchesOut)
def searchable_branches(repository_id: int | None = Query(None), db: Session = Depends(get_db), user: User = Depends(current_user), ws: int | None = Depends(active_workspace)):
    """Branches the caller can search: indexed/partial branches of repositories they have access to (optionally one repository)."""
    if repository_id is not None:
        get_repo_for_user(db, user, repository_id)
    q = (select(BranchIndexState.branch, Repository.default_branch, Repository.id)
         .join(Repository, Repository.id == BranchIndexState.repository_id).join(RepositoryAccess, RepositoryAccess.repository_id == Repository.id)
         .where(RepositoryAccess.user_id == user.id, Repository.is_enabled.is_(True), BranchIndexState.status.in_(["indexed", "partial"])))
    if repository_id is not None:
        q = q.where(Repository.id == repository_id)
    if ws is not None:
        q = q.where(Repository.workspace_id == ws)
    agg: dict[str, dict] = {}
    for branch, default, _rid in db.execute(q).all():
        a = agg.setdefault(branch, {"repositories": 0, "default": False})
        a["repositories"] += 1
        a["default"] = a["default"] or branch == default
    return SearchBranchesOut(branches=[SearchBranchOut(branch=b, repositories=v["repositories"], is_default_somewhere=v["default"])
                                       for b, v in sorted(agg.items(), key=lambda kv: (not kv[1]["default"], kv[0]))])


@router.post("/query", response_model=SearchOut, dependencies=[Depends(limit_search)])
def query(body: SearchIn, db: Session = Depends(get_db), user: User = Depends(current_user), s: Settings = Depends(settings_dep), ws: int | None = Depends(active_workspace)):
    ok, reason = indexing_available(s)
    if not ok:
        raise NotConfigured(REASONS[reason], code=reason)
    if body.repository_id is not None:
        get_repo_for_user(db, user, body.repository_id)  # 404 unless the caller has access
    q = (select(Repository).join(RepositoryAccess, RepositoryAccess.repository_id == Repository.id)
         .where(RepositoryAccess.user_id == user.id, Repository.is_enabled.is_(True)))
    if body.repository_id is not None:
        q = q.where(Repository.id == body.repository_id)
    if ws is not None:
        q = q.where(Repository.workspace_id == ws)  # the active workspace only (membership verified by active_workspace)
    accessible = db.scalars(q.order_by(Repository.full_name).limit(MAX_REPOS * 5)).all()
    # Which (repository, branch) pairs can be searched: the requested branch, or each repository's own default branch.
    states = {(rid, br): st for rid, br, st in db.execute(select(BranchIndexState.repository_id, BranchIndexState.branch, BranchIndexState.status)
                                                          .where(BranchIndexState.repository_id.in_([r.id for r in accessible] or [0])))}
    has_states = {rid for rid, _ in states}
    repos, branch_of = [], {}
    for r in accessible:
        eff = body.branch or r.default_branch
        st = states.get((r.id, eff))
        ok_state = st in ("indexed", "partial") or (st is None and r.id not in has_states and eff == r.default_branch and r.index_status in ("indexed", "partial"))  # pre-branch-state data
        if ok_state and len(repos) < MAX_REPOS:
            repos.append(r)
            branch_of[r.id] = eff
    store = get_vector_store(s)
    backend = store.label
    if not repos:
        what = f"on branch '{body.branch}'" if body.branch else "on their default branch"
        return SearchOut(results=[], searched_repositories=[], backend=backend, branch=body.branch,
                         note=f"None of your repositories is indexed {what}. Choose another branch, or index it from the Repositories page.")
    embedder = get_embedder(s)
    vec = embedder.embed([body.query])[0]
    check_dimensions([vec], s.embedding_dimensions)
    per_repo = []
    for r in repos:
        flt = build_filter(branch_of[r.id], body.language)  # the branch filter is ALWAYS applied: branches of one repository never mix in a result list
        matches = [m for m in store.query(namespace_for(r.id), vec, body.top_k, flt)
                   if int(m["metadata"].get("repo_id", -1)) == r.id and m["metadata"].get("branch") == branch_of[r.id]]  # defense in depth: repository AND branch
        per_repo.append(({"id": r.id, "full_name": r.full_name}, matches))
    hits = []
    merged = merge_results(per_repo, body.top_k)
    prs_by_repo = _related_prs(db, merged)
    for m in merged:
        md = m["metadata"]
        rel = pick_related_pr(md.get("branch"), md.get("commit"), prs_by_repo.get(m["repo"]["id"], []))
        hits.append(SearchHit(id=m["id"], score=round(float(m["score"]), 4), repository=m["repo"]["full_name"], repository_id=m["repo"]["id"], path=md.get("path", ""),
                              start_line=md.get("start_line"), end_line=md.get("end_line"), language=md.get("language") or None, branch=md.get("branch"),
                              commit=md.get("commit"), snippet=str(md.get("text", "")), explanation=explain_match(body.query, str(md.get("text", "")), md.get("path", ""), float(m["score"])),
                              github_url=github_blob_url(m["repo"]["full_name"], md.get("commit"), md.get("path", ""), md.get("start_line"), md.get("end_line")),
                              pull_request=PullRequestRef(**{k: rel[k] for k in ("id", "number", "title", "state", "html_url", "match")}) if rel else None))
    notes = []
    if getattr(embedder, "label", "").startswith("local"):
        notes.append("Local demo embeddings (lexical matching, not semantic).")
    skipped = [r.full_name for r in accessible if r not in repos]
    if body.branch and skipped:
        notes.append(f"Not searched (no index for branch '{body.branch}'): {', '.join(skipped[:5])}{' …' if len(skipped) > 5 else ''}.")
    return SearchOut(results=hits, searched_repositories=[r.full_name for r in repos], backend=backend, branch=body.branch, note=" ".join(notes) or None)
