"""Custom review rules. Instructions are untrusted config: validated here, wrapped as data at prompt time."""
from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.agents.llm import get_review_llm
from app.agents.review_graph import Limits, ReviewInput, run_review
from app.api.deps import current_user, rate_limit, settings_dep
from app.core.exceptions import Forbidden, NotFound
from app.db.session import get_db
from app.models import AuditLog, Repository, ReviewRule, User
from app.repositories.access import accessible_repo_ids, get_repo_for_user
from app.core.config import Settings
from app.schemas.rules import RuleIn, RuleOut, RulePatch, RuleTestIn, RuleTestOut
from app.services.diff_service import snippet_to_patch
from app.services.rule_validation import validate_rule_fields

router = APIRouter(prefix="/review-rules", tags=["review-rules"])
limit_test = rate_limit("rule_test", 10)


def _out(rule: ReviewRule, user: User, repo_names: dict[int, str]) -> RuleOut:
    return RuleOut(id=rule.id, name=rule.name, description=rule.description, instruction=rule.instruction, severity=rule.severity,
                   file_patterns=rule.file_patterns or [], languages=rule.languages or [], enabled=rule.enabled, repository_id=rule.repository_id,
                   repository=repo_names.get(rule.repository_id), is_demo=rule.is_demo, editable=rule.owner_user_id == user.id)


def _names(db: Session, rules) -> dict[int, str]:
    ids = {r.repository_id for r in rules if r.repository_id}
    return {r.id: r.full_name for r in db.scalars(select(Repository).where(Repository.id.in_(ids))).all()} if ids else {}


def _own_rule(db: Session, user: User, rule_id: int) -> ReviewRule:
    rule = db.get(ReviewRule, rule_id)
    if rule is None:
        raise NotFound("Rule not found")
    if rule.repository_id:
        get_repo_for_user(db, user, rule.repository_id)            # NotFound when no access
    if rule.owner_user_id != user.id:
        if rule.repository_id is None:
            raise NotFound("Rule not found")
        raise Forbidden("Only the rule's author can change it")
    if rule.repository_id:
        get_repo_for_user(db, user, rule.repository_id, require_owner=True)
    return rule


@router.get("", response_model=list[RuleOut])
def list_rules(repository_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(ReviewRule).where(or_(ReviewRule.owner_user_id == user.id, ReviewRule.repository_id.in_(accessible_repo_ids(db, user))))
    if repository_id:
        get_repo_for_user(db, user, repository_id)
        q = q.where(or_(ReviewRule.repository_id == repository_id, ReviewRule.repository_id.is_(None) & (ReviewRule.owner_user_id == user.id)))
    rules = db.scalars(q.order_by(ReviewRule.name)).all()
    names = _names(db, rules)
    return [_out(r, user, names) for r in rules]


@router.post("", response_model=RuleOut, status_code=201)
def create_rule(body: RuleIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.repository_id is not None:
        get_repo_for_user(db, user, body.repository_id, require_owner=True)
    v = validate_rule_fields(name=body.name, instruction=body.instruction, file_patterns=body.file_patterns, languages=body.languages)
    rule = ReviewRule(owner_user_id=user.id, repository_id=body.repository_id, description=body.description.strip(), severity=body.severity,
                      enabled=body.enabled, **v)
    db.add(rule)
    db.flush()
    db.add(AuditLog(user_id=user.id, action="rule.create", target_type="rule", target_id=str(rule.id)))
    db.commit()
    return _out(rule, user, _names(db, [rule]))


@router.patch("/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: int, body: RulePatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rule = _own_rule(db, user, rule_id)
    data = body.model_dump(exclude_unset=True)
    v = validate_rule_fields(name=data.get("name"), instruction=data.get("instruction"), file_patterns=data.get("file_patterns"), languages=data.get("languages"))
    for k, val in {**{k: val for k, val in data.items() if k in ("description", "severity", "enabled")}, **v}.items():
        setattr(rule, k, val.strip() if k == "description" and isinstance(val, str) else val)
    db.add(AuditLog(user_id=user.id, action="rule.update", target_type="rule", target_id=str(rule.id)))
    db.commit()
    return _out(rule, user, _names(db, [rule]))


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rule = _own_rule(db, user, rule_id)
    db.delete(rule)
    db.add(AuditLog(user_id=user.id, action="rule.delete", target_type="rule", target_id=str(rule_id)))
    db.commit()


@router.post("/test", response_model=RuleTestOut, dependencies=[Depends(limit_test)])
def test_rule(body: RuleTestIn, user: User = Depends(current_user), s: Settings = Depends(settings_dep)):
    """Runs ONE rule against a pasted snippet with the real engine. Nothing is stored or sent to GitHub."""
    from app.api.v1.reviews import confidence_label
    v = validate_rule_fields(instruction=body.instruction)
    llm = get_review_llm(s)  # 503 openai_not_configured when neither OpenAI nor the explicit mock is enabled
    patch, n = snippet_to_patch(body.code)
    rule = {"name": "Rule under test", "severity": body.severity, "instruction": v["instruction"], "enabled": True}
    result = run_review(ReviewInput(repo_id=0, pr_number=0, pr_title="Rule test", base_branch="main", head_branch="test",
                                    files=[{"filename": body.file_name, "status": "added", "patch": patch, "additions": n}], rules=[rule]),
                        llm, Limits(max_findings=10))
    findings = [{**f, "id": i, "status": "open", "confidence_label": confidence_label(f["confidence"]), "comment": None} for i, f in enumerate(result.findings, 1)]
    return RuleTestOut(findings=findings, summary=result.summary, model=result.model, mock="mock-llm" in result.model)
