"""Survey version history API endpoints — list, view, diff, restore."""

from __future__ import annotations

import difflib
import json
from copy import deepcopy
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from ...core.audit import log_audit
from ...core.collaboration import manager as collab_manager
from ...core.deps import check_survey_permission, get_current_user
from ...database import get_db
from ...models import Survey
from ...models.survey_version import SurveyVersion
from ...models.user import User
from ...schemas.survey import SurveyResponse
from ...schemas.version import (
    RestoreVersionRequest,
    VersionDetail,
    VersionDiffResponse,
    VersionListItem,
)

router = APIRouter(
    prefix="/surveys/{survey_id}/versions", tags=["versions"]
)


async def _get_creator_name(db: AsyncSession, creator_id: Optional[str]) -> Optional[str]:
    """Look up display_name for a creator, returning None if deleted."""
    if not creator_id:
        return None
    user = await db.get(User, creator_id)
    return user.display_name if user else None


@router.get("", response_model=list[VersionListItem])
async def list_versions(
    survey_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all saved versions of a survey, newest first."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    query = (
        select(SurveyVersion)
        .where(SurveyVersion.survey_id == sid)
        .order_by(SurveyVersion.version.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    versions = result.scalars().all()

    items = []
    for sv in versions:
        creator_name = await _get_creator_name(db, sv.creator_id)
        items.append(
            VersionListItem(
                id=sv.id,
                version=sv.version,
                title=sv.title,
                creator_name=creator_name,
                creator_id=sv.creator_id,
                changelog=sv.changelog,
                created_at=sv.created_at,
            )
        )
    return items


@router.get("/{version_id}", response_model=VersionDetail)
async def get_version(
    survey_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a specific version snapshot with full JSON content."""
    sid = str(survey_id)
    vid = str(version_id)
    await check_survey_permission(sid, user, "viewer", db)

    sv = await db.get(SurveyVersion, vid)
    if not sv or sv.survey_id != sid:
        raise HTTPException(status_code=404, detail="版本不存在")

    creator_name = await _get_creator_name(db, sv.creator_id)
    return VersionDetail(
        id=sv.id,
        version=sv.version,
        title=sv.title,
        description=sv.description,
        json_content=sv.json_content,
        creator_name=creator_name,
        creator_id=sv.creator_id,
        changelog=sv.changelog,
        created_at=sv.created_at,
    )


@router.post("/{version_id}/restore", response_model=SurveyResponse)
async def restore_version(
    survey_id: UUID,
    version_id: UUID,
    request: Request,
    body: Optional[RestoreVersionRequest] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Restore a survey to a previous version.

    Creates a new version snapshot of the current state *before* restoring,
    so the restore itself is reversible.
    """
    sid = str(survey_id)
    vid = str(version_id)
    await check_survey_permission(sid, user, "editor", db)

    # Fetch the snapshot to restore
    sv = await db.get(SurveyVersion, vid)
    if not sv or sv.survey_id != sid:
        raise HTTPException(status_code=404, detail="版本不存在")

    # Fetch the current survey
    survey = await db.get(Survey, sid)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")

    # Snapshot the current state before restoring (so restore is reversible)
    current_snapshot = SurveyVersion(
        survey_id=sid,
        version=survey.version,
        json_content=deepcopy(survey.json_content),
        title=survey.title,
        description=survey.description,
        creator_id=user.id,
        changelog=body.changelog
        if body
        else f"Restored from version {sv.version}",
    )
    db.add(current_snapshot)

    # Apply the snapshot content
    survey.title = sv.title
    survey.description = sv.description
    survey.json_content = deepcopy(sv.json_content)
    survey.version += 1

    # Create the restore snapshot as a new version entry
    restore_snapshot = SurveyVersion(
        survey_id=sid,
        version=survey.version,
        json_content=deepcopy(survey.json_content),
        title=survey.title,
        description=survey.description,
        creator_id=user.id,
        changelog=body.changelog
        if body
        else f"Restored from version {sv.version}",
    )
    db.add(restore_snapshot)

    await log_audit(
        db,
        action="survey.version.restore",
        user_id=user.id,
        resource_type="survey",
        resource_id=sid,
        details={
            "restored_from_version": sv.version,
            "previous_version": current_snapshot.version,
            "new_version": survey.version,
        },
        request=request,
    )

    await db.commit()
    await db.refresh(survey)

    # Notify live collaborators that the survey has changed.
    actor_conn_id = (
        request.headers.get("X-Collab-Connection-Id") if request else None
    )
    await collab_manager.broadcast_saved(
        survey_id=sid,
        version=survey.version,
        actor_user_id=user.id,
        actor_connection_id=actor_conn_id,
        updated_at=survey.updated_at,
    )

    return SurveyResponse.model_validate(survey)


@router.get("/diff", response_model=VersionDiffResponse)
async def diff_versions(
    survey_id: UUID,
    from_version: UUID = Query(..., alias="from"),
    to_version: UUID = Query(..., alias="to"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Compute a unified text diff between two versions."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    # Fetch both versions
    from_sv = await db.get(SurveyVersion, str(from_version))
    to_sv = await db.get(SurveyVersion, str(to_version))

    for sv, label in [(from_sv, "from"), (to_sv, "to")]:
        if not sv or sv.survey_id != sid:
            raise HTTPException(status_code=404, detail=f"'{label}' 版本不存在")

    # Build human-readable text representations
    from_text = json.dumps(from_sv.json_content, ensure_ascii=False, indent=2)
    to_text = json.dumps(to_sv.json_content, ensure_ascii=False, indent=2)

    from_label = f"Version {from_sv.version}"
    to_label = f"Version {to_sv.version}"

    diff_lines = list(
        difflib.unified_diff(
            from_text.splitlines(keepends=True),
            to_text.splitlines(keepends=True),
            fromfile=from_label,
            tofile=to_label,
        )
    )
    diff_text = "".join(diff_lines) if diff_lines else "（无差异）"

    from_creator = await _get_creator_name(db, from_sv.creator_id)
    to_creator = await _get_creator_name(db, to_sv.creator_id)

    return VersionDiffResponse(
        from_version=VersionListItem(
            id=from_sv.id,
            version=from_sv.version,
            title=from_sv.title,
            creator_name=from_creator,
            creator_id=from_sv.creator_id,
            changelog=from_sv.changelog,
            created_at=from_sv.created_at,
        ),
        to_version=VersionListItem(
            id=to_sv.id,
            version=to_sv.version,
            title=to_sv.title,
            creator_name=to_creator,
            creator_id=to_sv.creator_id,
            changelog=to_sv.changelog,
            created_at=to_sv.created_at,
        ),
        diff_text=diff_text,
    )
