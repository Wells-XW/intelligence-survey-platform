"""Survey CRUD API endpoints with authentication and authorization."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.audit import log_audit
from ...core.deps import check_survey_permission, get_current_user
from ...database import get_db
from ...models import Survey, SurveyPermission
from ...models.survey_version import SurveyVersion
from ...models.user import User
from ...schemas.survey import (
    CreateSurveyRequest,
    SurveyListItem,
    SurveyResponse,
    UpdateSurveyRequest,
)

router = APIRouter(prefix="/surveys", tags=["surveys"])


@router.get(
    "",
    response_model=list[SurveyListItem],
    summary="List the caller's surveys",
    description=(
        "Return surveys the authenticated user can access via any "
        "RBAC role (owner, editor, or viewer), newest-updated first. "
        "Filter optionally by ``status`` and paginate with "
        "``offset`` and ``limit`` (page size capped at 200)."
    ),
)
async def list_surveys(
    status: str | None = Query(default=None, description="Filter by status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List surveys the current user has access to, ordered by most recently updated."""
    query = (
        select(Survey)
        .join(SurveyPermission, Survey.id == SurveyPermission.survey_id)
        .where(SurveyPermission.user_id == user.id)
        .order_by(Survey.updated_at.desc())
    )
    if status:
        query = query.where(Survey.status == status)
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    surveys = result.scalars().all()
    return [SurveyListItem.model_validate(s) for s in surveys]


@router.post(
    "",
    response_model=SurveyResponse,
    status_code=201,
    summary="Create a new survey",
    description=(
        "Create a new survey owned by the authenticated user. The "
        "creating user is automatically granted the ``owner`` role "
        "via a fresh ``SurveyPermission`` row. Emits a "
        "``survey.create`` audit row."
    ),
)
async def create_survey(
    body: CreateSurveyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new survey. The creating user is automatically assigned as owner."""
    survey = Survey(
        title=body.title,
        description=body.description,
        json_content=body.json_content,
        owner_id=user.id,
    )
    db.add(survey)
    await db.flush()

    # Grant owner permission
    perm = SurveyPermission(user_id=user.id, survey_id=survey.id, role="owner")
    db.add(perm)

    await log_audit(
        db,
        action="survey.create",
        user_id=user.id,
        resource_type="survey",
        resource_id=survey.id,
        details={"title": body.title},
        request=request,
    )

    await db.commit()
    await db.refresh(survey)
    return SurveyResponse.model_validate(survey)


@router.get(
    "/{survey_id}",
    response_model=SurveyResponse,
    summary="Get a survey by id",
    description=(
        "Return one survey's full record including the SurveyJS "
        "``json_content`` payload. Caller must hold at least viewer "
        "permission. The response includes the optimistic-locking "
        "``version`` field used by ``PUT /{survey_id}``."
    ),
)
async def get_survey(
    survey_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a survey by ID. Requires at least viewer permission."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    result = await db.execute(select(Survey).where(Survey.id == sid))
    survey = result.scalar_one_or_none()
    # check_survey_permission already verified existence/permission
    return SurveyResponse.model_validate(survey)


@router.put(
    "/{survey_id}",
    response_model=SurveyResponse,
    summary="Update a survey",
    description=(
        "Apply a partial update to one survey. Supports "
        "optimistic-lock checking via ``expected_version`` (a 409 "
        "Conflict is returned when stale). Each successful update "
        "writes an immutable ``SurveyVersion`` snapshot for the "
        "version-history endpoints. Caller must hold editor or "
        "owner permission."
    ),
)
async def update_survey(
    survey_id: UUID,
    body: UpdateSurveyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a survey. Requires editor or owner permission.

    Optimistic-lock support: if ``expected_version`` is provided and
    differs from the server version, a 409 Conflict is returned so the
    client can reload and retry.

    Each successful update creates an immutable ``SurveyVersion`` snapshot.
    """
    sid = str(survey_id)
    await check_survey_permission(sid, user, "editor", db)

    result = await db.execute(select(Survey).where(Survey.id == sid))
    survey = result.scalar_one_or_none()

    # ── Optimistic lock check ──────────────────────────────────────
    expected_version = body.expected_version
    if expected_version is not None and expected_version != survey.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"问卷已被其他用户修改（当前版本 v{survey.version}，"
            f"你的版本 v{expected_version}）。请刷新后重试。",
        )

    # ── Apply updates ──────────────────────────────────────────────
    update_data = body.model_dump(
        exclude_unset=True, exclude={"expected_version"}
    )
    for key, value in update_data.items():
        setattr(survey, key, value)
    survey.version += 1

    # ── Create version snapshot ────────────────────────────────────
    snapshot = SurveyVersion(
        survey_id=sid,
        version=survey.version,
        json_content=deepcopy(survey.json_content),
        title=survey.title,
        description=survey.description,
        creator_id=user.id,
    )
    db.add(snapshot)

    # ── Audit ──────────────────────────────────────────────────────
    await log_audit(
        db,
        action="survey.update",
        user_id=user.id,
        resource_type="survey",
        resource_id=sid,
        details={"fields": list(update_data.keys())},
        request=request,
    )

    await db.commit()
    await db.refresh(survey)
    return SurveyResponse.model_validate(survey)


@router.delete(
    "/{survey_id}",
    status_code=204,
    summary="Delete a survey",
    description=(
        "Hard-delete one survey and all rows that cascade from it "
        "(responses, sample groups, distributions, version history). "
        "Restricted to the survey owner; this operation is not "
        "reversible. Emits a ``survey.delete`` audit row."
    ),
)
async def delete_survey(
    survey_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a survey. Only the owner can delete."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "owner", db)

    result = await db.execute(select(Survey).where(Survey.id == sid))
    survey = result.scalar_one_or_none()

    await log_audit(
        db,
        action="survey.delete",
        user_id=user.id,
        resource_type="survey",
        resource_id=sid,
        details={"title": survey.title if survey else None},
        request=request,
    )

    await db.delete(survey)
    await db.commit()
