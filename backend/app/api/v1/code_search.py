"""Semantic code search. Tenant isolation is enforced HERE (server side): only repositories the caller can
access through RepositoryAccess are ever queried, each in its own namespace; browser filters are never trusted."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, rate_limit, settings_dep
from app.core.config import Settings
from app.core.exceptions import NotConfigured
from app.db.session import get_db
from app.models import Repository, RepositoryAccess, User
from app.repositories.access import get_repo_for_user
from app.schemas.search import SearchHit, SearchIn, SearchOut
from app.services.embedding_service import check_dimensions, get_embedder
from app.services.index_policy import namespace_for
from app.services.search_logic import build_filter, explain_match, github_blob_url, merge_results
from app.services.vector_service import get_vector_store, indexing_available

router = APIRouter(prefix="/code-search", tags=["code-search"])
limit_search = rate_limit("code_search", "search_rate_limit_per_minute")
MAX_REPOS = 20
REASONS = {"pinecone_not_configured": "Pinecone is not configured. Set PINECONE_API_KEY and PINECONE_INDEX_NAME.",
           "openai_not_configured": "OpenAI is not configured. Set OPENAI_API_KEY to enable embeddings."}


@router.post("/query", response_model=SearchOut, dependencies=[Depends(limit_search)])
def query(body: SearchIn, db: Session = Depends(get_db), user: User = Depends(current_user), s: Settings = Depends(settings_dep)):
    ok, reason = indexing_available(s)
    if not ok:
        raise NotConfigured(REASONS[reason], code=reason)
    if body.repository_id is not None:
        get_repo_for_user(db, user, body.repository_id)  # 404 unless the caller has access
    q = (select(Repository).join(RepositoryAccess, RepositoryAccess.repository_id == Repository.id)
         .where(RepositoryAccess.user_id == user.id, Repository.is_enabled.is_(True), Repository.index_status == "indexed"))
    if body.repository_id is not None:
        q = q.where(Repository.id == body.repository_id)
    repos = db.scalars(q.order_by(Repository.full_name).limit(MAX_REPOS)).all()
    store = get_vector_store(s)
    backend = store.label
    if not repos:
        return SearchOut(results=[], searched_repositories=[], backend=backend, note="No indexed repositories are available to search. Connect a repository and run indexing first.")
    embedder = get_embedder(s)
    vec = embedder.embed([body.query])[0]
    check_dimensions([vec], s.embedding_dimensions)
    flt = build_filter(body.branch, body.language)
    per_repo = []
    for r in repos:
        matches = [m for m in store.query(namespace_for(r.id), vec, body.top_k, flt) if int(m["metadata"].get("repo_id", -1)) == r.id]  # defense in depth
        per_repo.append(({"id": r.id, "full_name": r.full_name}, matches))
    hits = []
    for m in merge_results(per_repo, body.top_k):
        md = m["metadata"]
        hits.append(SearchHit(id=m["id"], score=round(float(m["score"]), 4), repository=m["repo"]["full_name"], repository_id=m["repo"]["id"], path=md.get("path", ""),
                              start_line=md.get("start_line"), end_line=md.get("end_line"), language=md.get("language") or None, branch=md.get("branch"),
                              commit=md.get("commit"), snippet=str(md.get("text", "")), explanation=explain_match(body.query, str(md.get("text", "")), md.get("path", ""), float(m["score"])),
                              github_url=github_blob_url(m["repo"]["full_name"], md.get("commit"), md.get("path", ""), md.get("start_line"), md.get("end_line"))))
    note = "Local demo embeddings (lexical matching, not semantic)." if getattr(embedder, "label", "").startswith("local") else None
    return SearchOut(results=hits, searched_repositories=[r.full_name for r in repos], backend=backend, note=note)
