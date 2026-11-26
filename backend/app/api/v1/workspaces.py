"""Workspaces, members, invitations, workspace audit. Every route authorizes against workspace membership on the BACKEND (workspace_service.require_member);
non-members receive 404, members with too low a role 403."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_user, rate_limit
from app.db.session import get_db
from app.models import User
from app.schemas.workspaces import (AcceptIn, AuditEntryOut, InvitationCreate, InvitationCreated, InvitationOut, MemberOut, MyInvitationOut, RolePatch, TransferIn,
                                    WorkspaceCreate, WorkspaceDelete, WorkspaceOut, WorkspacePatch)
from app.services import workspace_service as svc

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
limit_invite = rate_limit("workspace_invite", 20, 3600, by="user")
limit_create = rate_limit("workspace_create", 10, 3600, by="user")


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return svc.list_for_user(db, user)


@router.post("", response_model=WorkspaceOut, status_code=201, dependencies=[Depends(limit_create)])
def create_workspace(body: WorkspaceCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ws = svc.create_workspace(db, user, body.name)
    return next(w for w in svc.list_for_user(db, user) if w["id"] == ws.id)


# -- invitations addressed to me (declared before /{workspace_id} so the static paths win) --
@router.get("/invitations/mine", response_model=list[MyInvitationOut])
def my_invitations(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return svc.my_invitations(db, user)


@router.post("/invitations/accept", response_model=WorkspaceOut, dependencies=[Depends(rate_limit("invitation_accept", 20, 3600, by="user"))])
def accept(body: AcceptIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ws = svc.accept_invitation(db, user, body.token)
    return next(w for w in svc.list_for_user(db, user) if w["id"] == ws.id)


@router.post("/invitations/{invitation_id}/decline", status_code=204)
def decline(invitation_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    svc.decline_my_invitation(db, user, invitation_id)


# -- one workspace --
@router.patch("/{workspace_id}", response_model=WorkspaceOut)
def update_workspace(workspace_id: int, body: WorkspacePatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    svc.update_workspace(db, user, workspace_id, name=body.name, invite_policy=body.invite_policy)
    return next(w for w in svc.list_for_user(db, user) if w["id"] == workspace_id)


@router.post("/{workspace_id}/delete", status_code=204)
def delete_workspace(workspace_id: int, body: WorkspaceDelete, db: Session = Depends(get_db), user: User = Depends(current_user)):
    svc.delete_workspace(db, user, workspace_id, body.confirm_name)


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
def members(workspace_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return svc.list_members(db, user, workspace_id)


@router.patch("/{workspace_id}/members/{user_id}", status_code=204)
def change_role(workspace_id: int, user_id: int, body: RolePatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    svc.change_role(db, user, workspace_id, user_id, body.role)


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(workspace_id: int, user_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    svc.remove_member(db, user, workspace_id, user_id)


@router.post("/{workspace_id}/leave", status_code=204)
def leave(workspace_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    svc.leave(db, user, workspace_id)


@router.post("/{workspace_id}/transfer", status_code=204)
def transfer(workspace_id: int, body: TransferIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    svc.transfer_ownership(db, user, workspace_id, body.user_id)


@router.get("/{workspace_id}/invitations", response_model=list[InvitationOut])
def invitations(workspace_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return svc.list_invitations(db, user, workspace_id)


@router.post("/{workspace_id}/invitations", response_model=InvitationCreated, status_code=201, dependencies=[Depends(limit_invite)])
def invite(workspace_id: int, body: InvitationCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    inv, token = svc.create_invitation(db, user, workspace_id, body.login, body.role)
    return InvitationCreated(id=inv.id, login=inv.invited_login, role=inv.role, status="pending", expires_at=inv.expires_at.isoformat(), created_at=inv.created_at.isoformat(), token=token)


@router.delete("/{workspace_id}/invitations/{invitation_id}", status_code=204)
def revoke(workspace_id: int, invitation_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    svc.revoke_invitation(db, user, workspace_id, invitation_id)


@router.get("/{workspace_id}/audit", response_model=list[AuditEntryOut])
def audit(workspace_id: int, limit: int = Query(100, ge=1, le=200), db: Session = Depends(get_db), user: User = Depends(current_user)):
    return svc.workspace_audit(db, user, workspace_id, limit)
