"""Permission management and collaboration invitation API endpoints.

Permissions:
    - viewer: can list permissions and invitations
    - editor: can view permissions
    - owner: can grant/revoke/update permissions and send/revoke invitations
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from ...core.audit import log_audit
from ...core.deps import check_survey_permission, get_current_user
from ...database import get_db
from ...models import Survey, SurveyPermission
from ...models.collaboration_invitation import CollaborationInvitation
from ...models.user import User
from ...schemas.permission import (
    CreateInvitationRequest,
    GrantPermissionRequest,
    InvitationAcceptResponse,
    InvitationResponse,
    PermissionDetail,
    UpdatePermissionRoleRequest,
    UserSearchItem,
)

# Prefixed permissions router (nested under surveys)
survey_permissions_router = APIRouter(
    prefix="/surveys/{survey_id}/permissions", tags=["permissions"]
)

# Prefixed invitations router (nested under surveys)
survey_invitations_router = APIRouter(
    prefix="/surveys/{survey_id}/invitations", tags=["invitations"]
)

# Standalone invitations router (public accept endpoint)
standalone_router = APIRouter(prefix="/invitations", tags=["invitations"])

# User search router
user_search_router = APIRouter(prefix="/users", tags=["users"])


# ── Permission endpoints ──────────────────────────────────────────────


@survey_permissions_router.get("", response_model=list[PermissionDetail])
async def list_permissions(
    survey_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all collaborators on a survey. Requires at least viewer access."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    query = (
        select(SurveyPermission, User.email, User.display_name)
        .join(User, SurveyPermission.user_id == User.id)
        .where(SurveyPermission.survey_id == sid)
        .order_by(SurveyPermission.created_at)
    )
    result = await db.execute(query)
    rows = result.all()

    return [
        PermissionDetail(
            id=row.SurveyPermission.id,
            user_id=row.SurveyPermission.user_id,
            user_email=row.email,
            user_display_name=row.display_name,
            role=row.SurveyPermission.role,
            created_at=row.SurveyPermission.created_at,
        )
        for row in rows
    ]


@survey_permissions_router.post(
    "", response_model=PermissionDetail, status_code=201
)
async def grant_permission(
    survey_id: UUID,
    body: GrantPermissionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Grant a new permission. Only the survey owner can do this."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "owner", db)

    # Validate target user exists
    target = await db.get(User, body.user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    # Cannot grant to self (already owner)
    if body.user_id == user.id:
        raise HTTPException(status_code=409, detail="你已是该问卷的所有者")

    # Check for existing permission
    existing = await db.execute(
        select(SurveyPermission).where(
            and_(
                SurveyPermission.survey_id == sid,
                SurveyPermission.user_id == body.user_id,
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="该用户已是协作者")

    perm = SurveyPermission(
        user_id=body.user_id, survey_id=sid, role=body.role
    )
    db.add(perm)

    await log_audit(
        db,
        action="survey.permission.grant",
        user_id=user.id,
        resource_type="survey",
        resource_id=sid,
        details={"target_user_id": body.user_id, "role": body.role},
        request=request,
    )

    await db.commit()
    await db.refresh(perm)

    return PermissionDetail(
        id=perm.id,
        user_id=perm.user_id,
        user_email=target.email,
        user_display_name=target.display_name,
        role=perm.role,
        created_at=perm.created_at,
    )


@survey_permissions_router.put(
    "/{permission_id}", response_model=PermissionDetail
)
async def update_permission_role(
    survey_id: UUID,
    permission_id: UUID,
    body: UpdatePermissionRoleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a collaborator's role. Only the owner can do this."""
    sid = str(survey_id)
    pid = str(permission_id)
    await check_survey_permission(sid, user, "owner", db)

    perm = await db.get(SurveyPermission, pid)
    if not perm or perm.survey_id != sid:
        raise HTTPException(status_code=404, detail="权限记录不存在")

    # Cannot change the owner role
    if perm.role == "owner":
        raise HTTPException(status_code=400, detail="无法更改所有者的角色")

    old_role = perm.role
    perm.role = body.role

    await log_audit(
        db,
        action="survey.permission.update",
        user_id=user.id,
        resource_type="survey",
        resource_id=sid,
        details={
            "permission_id": pid,
            "target_user_id": perm.user_id,
            "old_role": old_role,
            "new_role": body.role,
        },
        request=request,
    )

    await db.commit()
    await db.refresh(perm)

    target = await db.get(User, perm.user_id)
    return PermissionDetail(
        id=perm.id,
        user_id=perm.user_id,
        user_email=target.email if target else "",
        user_display_name=target.display_name if target else "Deleted User",
        role=perm.role,
        created_at=perm.created_at,
    )


@survey_permissions_router.delete("/{permission_id}", status_code=204)
async def revoke_permission(
    survey_id: UUID,
    permission_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Revoke a collaborator's access. Only the owner can do this."""
    sid = str(survey_id)
    pid = str(permission_id)
    await check_survey_permission(sid, user, "owner", db)

    perm = await db.get(SurveyPermission, pid)
    if not perm or perm.survey_id != sid:
        raise HTTPException(status_code=404, detail="权限记录不存在")

    # Cannot revoke owner
    if perm.role == "owner":
        raise HTTPException(status_code=400, detail="无法移除所有者的权限")

    await log_audit(
        db,
        action="survey.permission.revoke",
        user_id=user.id,
        resource_type="survey",
        resource_id=sid,
        details={"permission_id": pid, "target_user_id": perm.user_id},
        request=request,
    )

    await db.delete(perm)
    await db.commit()


# ── Invitation endpoints (nested under surveys) ───────────────────────


def _build_invite_url(token: str) -> str:
    """Build the frontend URL for accepting an invitation."""
    from ...config import settings

    base = getattr(settings, "frontend_url", "http://localhost:5173")
    return f"{base}/invite/{token}"


@survey_invitations_router.post(
    "", response_model=InvitationResponse, status_code=201
)
async def create_invitation(
    survey_id: UUID,
    body: CreateInvitationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Send a collaboration invitation. Only the owner can invite."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "owner", db)

    # Check if email is already a collaborator
    existing_perm = await db.execute(
        select(SurveyPermission, User.email)
        .join(User, SurveyPermission.user_id == User.id)
        .where(
            and_(
                SurveyPermission.survey_id == sid,
                User.email == body.email.lower().strip(),
            )
        )
    )
    if existing_perm.first():
        raise HTTPException(status_code=409, detail="该用户已是协作者")

    # Check if pending invitation already exists
    existing_inv = await db.execute(
        select(CollaborationInvitation).where(
            and_(
                CollaborationInvitation.survey_id == sid,
                CollaborationInvitation.email == body.email.lower().strip(),
                CollaborationInvitation.status == "pending",
            )
        )
    )
    if existing_inv.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="该邮箱已有待处理的邀请")

    token = secrets.token_urlsafe(32)
    invitation = CollaborationInvitation(
        survey_id=sid,
        inviter_id=user.id,
        email=body.email.lower().strip(),
        role=body.role,
        token=token,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(invitation)

    await log_audit(
        db,
        action="survey.invitation.send",
        user_id=user.id,
        resource_type="survey",
        resource_id=sid,
        details={"email": body.email, "role": body.role},
        request=request,
    )

    await db.commit()
    await db.refresh(invitation)

    return InvitationResponse(
        id=invitation.id,
        survey_id=invitation.survey_id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        token=invitation.token,
        invite_url=_build_invite_url(invitation.token),
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


@survey_invitations_router.get("", response_model=list[InvitationResponse])
async def list_invitations(
    survey_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List pending invitations for a survey. Owner only."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "owner", db)

    result = await db.execute(
        select(CollaborationInvitation)
        .where(CollaborationInvitation.survey_id == sid)
        .order_by(CollaborationInvitation.created_at.desc())
    )
    invitations = result.scalars().all()

    return [
        InvitationResponse(
            id=inv.id,
            survey_id=inv.survey_id,
            email=inv.email,
            role=inv.role,
            status=inv.status,
            token=inv.token,
            invite_url=_build_invite_url(inv.token),
            expires_at=inv.expires_at,
            created_at=inv.created_at,
        )
        for inv in invitations
    ]


@survey_invitations_router.delete("/{invitation_id}", status_code=204)
async def revoke_invitation(
    survey_id: UUID,
    invitation_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Revoke a pending invitation. Owner only."""
    sid = str(survey_id)
    iid = str(invitation_id)
    await check_survey_permission(sid, user, "owner", db)

    invitation = await db.get(CollaborationInvitation, iid)
    if not invitation or invitation.survey_id != sid:
        raise HTTPException(status_code=404, detail="邀请不存在")

    invitation.status = "expired"

    await log_audit(
        db,
        action="survey.invitation.revoke",
        user_id=user.id,
        resource_type="survey",
        resource_id=sid,
        details={"invitation_id": iid, "email": invitation.email},
        request=request,
    )

    await db.commit()


# ── Public invitation endpoints ───────────────────────────────────────


@standalone_router.get("/{token}", response_model=InvitationResponse)
async def lookup_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Look up an invitation by token. Requires authentication."""
    result = await db.execute(
        select(CollaborationInvitation, Survey.title)
        .join(Survey, CollaborationInvitation.survey_id == Survey.id)
        .where(CollaborationInvitation.token == token)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="邀请链接无效")

    invitation = row.CollaborationInvitation

    # Check for expired
    if invitation.status == "expired" or invitation.expires_at < datetime.now(
        timezone.utc
    ):
        if invitation.status == "pending":
            invitation.status = "expired"
            await db.commit()
        raise HTTPException(status_code=410, detail="邀请链接已过期")

    if invitation.status != "pending":
        status_map = {
            "accepted": "此邀请已被接受",
            "declined": "此邀请已被拒绝",
            "expired": "此邀请已过期",
        }
        raise HTTPException(
            status_code=410,
            detail=status_map.get(invitation.status, "邀请已失效"),
        )

    return InvitationResponse(
        id=invitation.id,
        survey_id=invitation.survey_id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        token=invitation.token,
        invite_url=_build_invite_url(invitation.token),
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


@standalone_router.post(
    "/{token}/accept", response_model=InvitationAcceptResponse, status_code=201
)
async def accept_invitation(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Accept a collaboration invitation.

    Creates a SurveyPermission row for the accepting user.  The
    accepting user's email must match the invitation email.
    """
    result = await db.execute(
        select(CollaborationInvitation, Survey.title, Survey.id)
        .join(Survey, CollaborationInvitation.survey_id == Survey.id)
        .where(CollaborationInvitation.token == token)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="邀请链接无效")

    invitation = row.CollaborationInvitation
    survey_title = row.title
    survey_id = row.id

    # Validate status
    if invitation.status != "pending":
        raise HTTPException(status_code=410, detail="该邀请已失效")

    if invitation.expires_at < datetime.now(timezone.utc):
        invitation.status = "expired"
        await db.commit()
        raise HTTPException(status_code=410, detail="邀请链接已过期")

    # Verify email match
    if invitation.email.lower() != user.email.lower():
        raise HTTPException(
            status_code=403,
            detail=f"此邀请是发送给 {invitation.email} 的，与你的账号邮箱不匹配。"
            f"请使用 {invitation.email} 登录后接受邀请。",
        )

    # Check if already a collaborator
    existing = await db.execute(
        select(SurveyPermission).where(
            and_(
                SurveyPermission.survey_id == survey_id,
                SurveyPermission.user_id == user.id,
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="你已是该问卷的协作者")

    # Create permission
    perm = SurveyPermission(
        user_id=user.id, survey_id=survey_id, role=invitation.role
    )
    db.add(perm)

    # Update invitation
    invitation.status = "accepted"
    invitation.accepted_at = datetime.now(timezone.utc)

    await log_audit(
        db,
        action="survey.invitation.accept",
        user_id=user.id,
        resource_type="survey",
        resource_id=survey_id,
        details={
            "invitation_id": invitation.id,
            "role": invitation.role,
            "inviter_id": invitation.inviter_id,
        },
        request=request,
    )

    await db.commit()
    await db.refresh(perm)

    return InvitationAcceptResponse(
        permission=PermissionDetail(
            id=perm.id,
            user_id=perm.user_id,
            user_email=user.email,
            user_display_name=user.display_name,
            role=perm.role,
            created_at=perm.created_at,
        ),
        survey_title=survey_title,
        survey_id=survey_id,
    )


# ── User search endpoint ──────────────────────────────────────────────


@user_search_router.get("/search", response_model=list[UserSearchItem])
async def search_users(
    q: str = Query(..., min_length=1, max_length=320, description="Email prefix"),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Search users by email prefix for the collaboration dialog."""
    query = (
        select(User.id, User.email, User.display_name)
        .where(User.email.ilike(f"{q}%"))
        .limit(limit)
    )
    result = await db.execute(query)
    rows = result.all()

    return [
        UserSearchItem(id=row.id, email=row.email, display_name=row.display_name)
        for row in rows
    ]
