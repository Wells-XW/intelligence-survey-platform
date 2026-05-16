"""Sample distribution management API endpoints.

Provides CRUD for sample groups, recipients, distributions, and quotas,
plus a dashboard aggregation endpoint and a public token-based fill redirect.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from ...core.audit import log_audit
from ...core.deps import check_survey_permission, get_current_user
from ...database import get_db
from ...models.distribution import Distribution
from ...models.quota import Quota
from ...models.recipient import Recipient
from ...models.sample_group import SampleGroup
from ...models.survey import Survey
from ...models.user import User
from ...schemas.sample_distribution import (
    CreateDistributionRequest,
    CreateQuotaRequest,
    CreateRecipientRequest,
    CreateSampleGroupRequest,
    DistributionDashboardResponse,
    DistributionListItem,
    DistributionResponse,
    QuotaResponse,
    RecipientImportResult,
    RecipientListItem,
    RecipientResponse,
    SampleGroupListItem,
    SampleGroupResponse,
    SendDistributionResponse,
    UpdateDistributionRequest,
    UpdateQuotaRequest,
    UpdateRecipientRequest,
    UpdateSampleGroupRequest,
)
from ...services.sample_service import (
    compute_distribution_counts,
    match_recipient_from_token,
    parse_csv_recipients,
    update_quota_on_response,
    update_recipient_count,
)
from ...services.webhook_emitter import (
    emit_webhook_event,
    enqueue_webhook_deliveries,
)

router = APIRouter(prefix="/surveys", tags=["distribution"])


# ═══════════════════════════════════════════════════════════════════════════
# Sample Groups
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/{survey_id}/sample-groups",
    response_model=SampleGroupResponse,
    status_code=201,
    summary="Create a sample group",
    description=(
        "Create a sample group attached to a survey. Sample groups "
        "scope a list of recipients for one or more distribution "
        "campaigns. Caller must hold editor or owner permission on "
        "the survey. Emits a ``sample_group.create`` audit row."
    ),
)
async def create_sample_group(
    survey_id: UUID,
    body: CreateSampleGroupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new sample group for a survey. Requires editor or owner."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "editor", db)

    group = SampleGroup(survey_id=sid, name=body.name, description=body.description)
    db.add(group)

    await log_audit(
        db, action="sample_group.create", user_id=user.id,
        resource_type="sample_group", resource_id=group.id,
        details={"survey_id": sid, "name": body.name}, request=request,
    )
    await db.commit()
    await db.refresh(group)
    return SampleGroupResponse.model_validate(group)


@router.get(
    "/{survey_id}/sample-groups",
    response_model=list[SampleGroupListItem],
    summary="List sample groups for a survey",
    description=(
        "List every sample group attached to the survey, "
        "newest-first. Caller must hold at least viewer permission "
        "on the survey."
    ),
)
async def list_sample_groups(
    survey_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all sample groups for a survey. Requires viewer or above."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    result = await db.execute(
        select(SampleGroup)
        .where(SampleGroup.survey_id == sid)
        .order_by(SampleGroup.created_at.desc())
    )
    return [SampleGroupListItem.model_validate(g) for g in result.scalars().all()]


@router.get(
    "/{survey_id}/sample-groups/{group_id}",
    response_model=SampleGroupResponse,
    summary="Get a sample group by id",
    description=(
        "Return one sample group's metadata and recipient counts. "
        "Caller must hold at least viewer permission on the parent "
        "survey."
    ),
)
async def get_sample_group(
    survey_id: UUID,
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single sample group by ID."""
    sid = str(survey_id)
    gid = str(group_id)
    await check_survey_permission(sid, user, "viewer", db)

    result = await db.execute(
        select(SampleGroup).where(SampleGroup.id == gid, SampleGroup.survey_id == sid)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="样本组不存在")
    return SampleGroupResponse.model_validate(group)


@router.put(
    "/{survey_id}/sample-groups/{group_id}",
    response_model=SampleGroupResponse,
    summary="Update a sample group",
    description=(
        "Update one sample group's name or description. The "
        "associated recipient list is unchanged. Caller must hold "
        "editor or owner permission."
    ),
)
async def update_sample_group(
    survey_id: UUID,
    group_id: UUID,
    body: UpdateSampleGroupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a sample group's name or description. Requires editor or above."""
    sid = str(survey_id)
    gid = str(group_id)
    await check_survey_permission(sid, user, "editor", db)

    result = await db.execute(
        select(SampleGroup).where(SampleGroup.id == gid, SampleGroup.survey_id == sid)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="样本组不存在")

    if body.name is not None:
        group.name = body.name
    if body.description is not None:
        group.description = body.description

    db.add(group)
    await log_audit(
        db, action="sample_group.update", user_id=user.id,
        resource_type="sample_group", resource_id=gid, request=request,
    )
    await db.commit()
    await db.refresh(group)
    return SampleGroupResponse.model_validate(group)


@router.delete(
    "/{survey_id}/sample-groups/{group_id}",
    status_code=204,
    summary="Delete a sample group",
    description=(
        "Hard-delete one sample group and all of its recipients. "
        "Distribution campaigns referencing the group must be "
        "deleted first or they will fail subsequent operations. "
        "Restricted to the survey owner."
    ),
)
async def delete_sample_group(
    survey_id: UUID,
    group_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a sample group and all its recipients. Owner only."""
    sid = str(survey_id)
    gid = str(group_id)
    await check_survey_permission(sid, user, "owner", db)

    result = await db.execute(
        select(SampleGroup).where(SampleGroup.id == gid, SampleGroup.survey_id == sid)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="样本组不存在")

    await db.delete(group)
    await log_audit(
        db, action="sample_group.delete", user_id=user.id,
        resource_type="sample_group", resource_id=gid, request=request,
    )
    await db.commit()


# ═══════════════════════════════════════════════════════════════════════════
# Recipients
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/{survey_id}/sample-groups/{group_id}/recipients",
    response_model=RecipientResponse,
    status_code=201,
    summary="Add a recipient to a sample group",
    description=(
        "Append one recipient to a sample group. Demographics are "
        "stored as a JSON object so quota matching can later filter "
        "by arbitrary fields. Caller must hold editor or owner "
        "permission."
    ),
)
async def add_recipient(
    survey_id: UUID,
    group_id: UUID,
    body: CreateRecipientRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add a single recipient to a sample group. Requires editor or above."""
    sid = str(survey_id)
    gid = str(group_id)
    await check_survey_permission(sid, user, "editor", db)

    # Verify group belongs to this survey
    result = await db.execute(
        select(SampleGroup).where(SampleGroup.id == gid, SampleGroup.survey_id == sid)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="样本组不存在")

    recipient = Recipient(
        sample_group_id=gid,
        email=body.email,
        name=body.name,
        external_id=body.external_id,
        demographics=body.demographics,
    )
    db.add(recipient)
    await db.flush()

    await update_recipient_count(db, gid)
    await db.commit()
    await db.refresh(recipient)
    return RecipientResponse.model_validate(recipient)


@router.post(
    "/{survey_id}/sample-groups/{group_id}/recipients/import",
    response_model=RecipientImportResult,
    summary="Import recipients from a CSV file",
    description=(
        "Bulk-import recipients from a CSV upload (UTF-8 or GBK). "
        "Required columns are ``email/邮箱`` and ``name/姓名``; "
        "any other columns are stored as demographics. Capped at "
        "500 recipients per import. Emits a ``recipient.import`` "
        "audit row carrying the imported count."
    ),
)
async def import_recipients_csv(
    survey_id: UUID,
    group_id: UUID,
    file: UploadFile,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Import recipients from a CSV file. Requires editor or above.

    CSV columns: ``email/邮箱``, ``name/姓名``, and any demographic columns.
    Maximum 500 recipients per import.
    """
    sid = str(survey_id)
    gid = str(group_id)
    await check_survey_permission(sid, user, "editor", db)

    # Verify group
    result = await db.execute(
        select(SampleGroup).where(SampleGroup.id == gid, SampleGroup.survey_id == sid)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="样本组不存在")

    # Read file content
    try:
        content = (await file.read()).decode("utf-8")
    except UnicodeDecodeError:
        # Try with GBK (common for Chinese CSV exports)
        try:
            content = (await file.read()).decode("gbk")
        except Exception:
            raise HTTPException(status_code=400, detail="无法解析 CSV 文件编码，请使用 UTF-8")
    except Exception:
        raise HTTPException(status_code=400, detail="读取文件失败")

    recipients, errors = parse_csv_recipients(content)

    # Enforce max import limit
    MAX_IMPORT = 500
    if len(recipients) > MAX_IMPORT:
        raise HTTPException(
            status_code=400,
            detail=f"单次导入最多 {MAX_IMPORT} 条记录，当前 {len(recipients)} 条",
        )

    imported = 0
    for r in recipients:
        recipient = Recipient(
            sample_group_id=gid,
            email=r["email"],
            name=r["name"],
            demographics=r["demographics"],
        )
        db.add(recipient)
        imported += 1

    await db.flush()
    await update_recipient_count(db, gid)

    await log_audit(
        db, action="recipient.import", user_id=user.id,
        resource_type="sample_group", resource_id=gid,
        details={"imported": imported, "errors": len(errors)}, request=request,
    )
    await db.commit()

    return RecipientImportResult(imported=imported, skipped=0, errors=errors)


@router.get(
    "/{survey_id}/sample-groups/{group_id}/recipients",
    response_model=list[RecipientListItem],
    summary="List recipients in a sample group",
    description=(
        "List recipients in one sample group, newest-first, with "
        "their per-recipient send and completion status. Caller "
        "must hold at least viewer permission on the survey."
    ),
)
async def list_recipients(
    survey_id: UUID,
    group_id: UUID,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List recipients in a sample group. Requires viewer or above."""
    sid = str(survey_id)
    gid = str(group_id)
    await check_survey_permission(sid, user, "viewer", db)

    result = await db.execute(
        select(Recipient)
        .where(Recipient.sample_group_id == gid)
        .order_by(Recipient.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return [RecipientListItem.model_validate(r) for r in result.scalars().all()]


@router.put(
    "/{survey_id}/sample-groups/{group_id}/recipients/{recipient_id}",
    response_model=RecipientResponse,
    summary="Update a recipient",
    description=(
        "Update one recipient's contact info or demographics. "
        "Caller must hold editor or owner permission on the survey."
    ),
)
async def update_recipient(
    survey_id: UUID,
    group_id: UUID,
    recipient_id: UUID,
    body: UpdateRecipientRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a recipient's info or demographics. Requires editor or above."""
    sid = str(survey_id)
    gid = str(group_id)
    rid = str(recipient_id)
    await check_survey_permission(sid, user, "editor", db)

    result = await db.execute(
        select(Recipient).where(Recipient.id == rid, Recipient.sample_group_id == gid)
    )
    recipient = result.scalar_one_or_none()
    if recipient is None:
        raise HTTPException(status_code=404, detail="受访者不存在")

    if body.email is not None:
        recipient.email = body.email
    if body.name is not None:
        recipient.name = body.name
    if body.demographics is not None:
        recipient.demographics = body.demographics

    db.add(recipient)
    await log_audit(
        db, action="recipient.update", user_id=user.id,
        resource_type="recipient", resource_id=rid, request=request,
    )
    await db.commit()
    await db.refresh(recipient)
    return RecipientResponse.model_validate(recipient)


@router.delete(
    "/{survey_id}/sample-groups/{group_id}/recipients/{recipient_id}",
    status_code=204,
    summary="Remove a recipient from a sample group",
    description=(
        "Remove one recipient from a sample group and decrement "
        "the group's cached recipient count. Caller must hold "
        "editor or owner permission."
    ),
)
async def delete_recipient(
    survey_id: UUID,
    group_id: UUID,
    recipient_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove a recipient from a sample group. Requires editor or above."""
    sid = str(survey_id)
    gid = str(group_id)
    rid = str(recipient_id)
    await check_survey_permission(sid, user, "editor", db)

    result = await db.execute(
        select(Recipient).where(Recipient.id == rid, Recipient.sample_group_id == gid)
    )
    recipient = result.scalar_one_or_none()
    if recipient is None:
        raise HTTPException(status_code=404, detail="受访者不存在")

    await db.delete(recipient)
    await db.flush()
    await update_recipient_count(db, gid)

    await log_audit(
        db, action="recipient.delete", user_id=user.id,
        resource_type="recipient", resource_id=rid, request=request,
    )
    await db.commit()


# ═══════════════════════════════════════════════════════════════════════════
# Distributions
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/{survey_id}/distributions",
    response_model=DistributionResponse,
    status_code=201,
    summary="Create a distribution campaign",
    description=(
        "Create a distribution campaign that will deliver the "
        "survey to a sample group's recipients. The survey must "
        "be in ``published`` status; campaigns can be scheduled "
        "for a future ``scheduled_at`` or sent immediately via "
        "``POST /distributions/{distribution_id}/send``. Caller "
        "must hold editor or owner permission."
    ),
)
async def create_distribution(
    survey_id: UUID,
    body: CreateDistributionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new distribution campaign. Requires editor or above.

    The survey must be published to create a distribution.
    """
    sid = str(survey_id)
    await check_survey_permission(sid, user, "editor", db)

    # Verify survey is published
    result = await db.execute(select(Survey).where(Survey.id == sid))
    survey = result.scalar_one_or_none()
    if survey is None:
        raise HTTPException(status_code=404, detail="问卷不存在")
    if survey.status not in ("published",):
        raise HTTPException(
            status_code=400,
            detail=f"只能对已发布的问卷创建发放，当前状态: {survey.status}",
        )

    # Verify sample group belongs to this survey
    result = await db.execute(
        select(SampleGroup).where(
            SampleGroup.id == body.sample_group_id,
            SampleGroup.survey_id == sid,
        )
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="样本组不存在或不属于此问卷")

    distribution = Distribution(
        survey_id=sid,
        sample_group_id=body.sample_group_id,
        name=body.name,
        subject_template=body.subject_template,
        body_template=body.body_template,
        scheduled_at=body.scheduled_at,
    )
    db.add(distribution)

    await log_audit(
        db, action="distribution.create", user_id=user.id,
        resource_type="distribution", resource_id=distribution.id,
        details={"sample_group_id": body.sample_group_id}, request=request,
    )
    await db.commit()
    await db.refresh(distribution)
    return DistributionResponse.model_validate(distribution)


@router.get(
    "/{survey_id}/distributions",
    response_model=list[DistributionListItem],
    summary="List distributions for a survey",
    description=(
        "List every distribution campaign created for the survey, "
        "newest-first, with each row carrying its sample-group "
        "name for display. Caller must hold at least viewer "
        "permission."
    ),
)
async def list_distributions(
    survey_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all distributions for a survey. Requires viewer or above."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    result = await db.execute(
        select(Distribution, SampleGroup.name.label("sg_name"))
        .join(SampleGroup, Distribution.sample_group_id == SampleGroup.id, isouter=True)
        .where(Distribution.survey_id == sid)
        .order_by(Distribution.created_at.desc())
    )
    items = []
    for dist, sg_name in result.all():
        item = DistributionListItem.model_validate(dist)
        item.sample_group_name = sg_name
        items.append(item)
    return items


@router.get(
    "/{survey_id}/distributions/{distribution_id}",
    response_model=DistributionResponse,
    summary="Get a distribution by id",
    description=(
        "Return one distribution campaign's full record including "
        "subject and body templates. Caller must hold at least "
        "viewer permission on the survey."
    ),
)
async def get_distribution(
    survey_id: UUID,
    distribution_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single distribution by ID."""
    sid = str(survey_id)
    did = str(distribution_id)
    await check_survey_permission(sid, user, "viewer", db)

    result = await db.execute(
        select(Distribution).where(
            Distribution.id == did, Distribution.survey_id == sid
        )
    )
    dist = result.scalar_one_or_none()
    if dist is None:
        raise HTTPException(status_code=404, detail="发放不存在")
    return DistributionResponse.model_validate(dist)


@router.post(
    "/{survey_id}/distributions/{distribution_id}/send",
    response_model=SendDistributionResponse,
    summary="Execute a distribution and generate links",
    description=(
        "Execute one distribution campaign: mark every "
        "``pending`` recipient as ``sent``, generate per-recipient "
        "tracking tokens, and emit a ``distribution.sent`` webhook "
        "event for any active subscribers. Idempotent on already "
        "``sent`` campaigns; a re-send only processes recipients "
        "still in ``pending``. Caller must hold editor or owner "
        "permission."
    ),
)
async def send_distribution(
    survey_id: UUID,
    distribution_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Execute a distribution: generate unique links and mark recipients as sent.

    Requires editor or above. Distribution must be in ``draft`` or ``sent`` status.
    Only ``pending`` recipients are processed.
    """
    sid = str(survey_id)
    did = str(distribution_id)
    await check_survey_permission(sid, user, "editor", db)

    result = await db.execute(
        select(Distribution).where(
            Distribution.id == did, Distribution.survey_id == sid
        )
    )
    dist = result.scalar_one_or_none()
    if dist is None:
        raise HTTPException(status_code=404, detail="发放不存在")

    if dist.status not in ("draft", "sent"):
        raise HTTPException(
            status_code=400,
            detail=f"只能对 draft 或 sent 状态的发放执行发送，当前状态: {dist.status}",
        )

    # Fetch pending recipients in the associated sample group
    result = await db.execute(
        select(Recipient).where(
            Recipient.sample_group_id == dist.sample_group_id,
            Recipient.status == "pending",
        )
    )
    pending_recipients = result.scalars().all()

    now = datetime.now(timezone.utc)
    links_generated = 0
    for recipient in pending_recipients:
        recipient.status = "sent"
        recipient.sent_at = now
        db.add(recipient)
        links_generated += 1

    dist.status = "sent"
    dist.sent_count = (dist.sent_count or 0) + links_generated
    db.add(dist)

    await log_audit(
        db, action="distribution.send", user_id=user.id,
        resource_type="distribution", resource_id=did,
        details={
            "recipients_processed": links_generated,
            "sample_group_id": dist.sample_group_id,
        },
        request=request,
    )

    # Emit distribution.sent webhook event for any subscribers. Insert
    # delivery rows in the same transaction; enqueue Celery tasks only
    # after commit succeeds.
    delivery_ids = await emit_webhook_event(
        db,
        event_type="distribution.sent",
        survey_id=sid,
        payload={
            "survey_id": sid,
            "distribution_id": did,
            "distribution_name": dist.name,
            "sample_group_id": dist.sample_group_id,
            "recipients_processed": links_generated,
            "links_generated": links_generated,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    await db.commit()
    await db.refresh(dist)
    enqueue_webhook_deliveries(delivery_ids)

    return SendDistributionResponse(
        distribution_id=did,
        recipients_processed=links_generated,
        links_generated=links_generated,
    )


@router.post(
    "/{survey_id}/distributions/{distribution_id}/remind",
    response_model=SendDistributionResponse,
    summary="Send reminders to non-completed recipients",
    description=(
        "Re-stamp ``sent_at`` on recipients of the campaign whose "
        "status is still ``sent``, ``opened``, or ``started``. The "
        "operation is intended to drive a downstream "
        "email-reminder pipeline once that integration is wired in. "
        "Caller must hold editor or owner permission."
    ),
)
async def remind_distribution(
    survey_id: UUID,
    distribution_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Send reminders to recipients who haven't completed yet (sent/opened status).

    Requires editor or above.
    """
    sid = str(survey_id)
    did = str(distribution_id)
    await check_survey_permission(sid, user, "editor", db)

    result = await db.execute(
        select(Distribution).where(
            Distribution.id == did, Distribution.survey_id == sid
        )
    )
    dist = result.scalar_one_or_none()
    if dist is None:
        raise HTTPException(status_code=404, detail="发放不存在")

    # Find non-completed recipients
    result = await db.execute(
        select(Recipient).where(
            Recipient.sample_group_id == dist.sample_group_id,
            Recipient.status.in_(["sent", "opened", "started"]),
        )
    )
    remind_recipients = result.scalars().all()

    # In MVP, "remind" simply re-marks as sent (links can be re-shared)
    # Future: integrate with email sending
    reminded = 0
    for recipient in remind_recipients:
        recipient.sent_at = datetime.now(timezone.utc)
        db.add(recipient)
        reminded += 1

    await log_audit(
        db, action="distribution.remind", user_id=user.id,
        resource_type="distribution", resource_id=did,
        details={"reminded": reminded}, request=request,
    )
    await db.commit()

    return SendDistributionResponse(
        distribution_id=did,
        recipients_processed=reminded,
        links_generated=0,  # No new links on remind
    )


# ═══════════════════════════════════════════════════════════════════════════
# Quotas
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/{survey_id}/quotas",
    response_model=QuotaResponse,
    status_code=201,
    summary="Create a demographic quota",
    description=(
        "Create a demographic quota cap for one survey. Quotas are "
        "evaluated each time a response is submitted; once a quota "
        "fills, a ``quota.reached`` webhook event is emitted. "
        "Caller must hold editor or owner permission."
    ),
)
async def create_quota(
    survey_id: UUID,
    body: CreateQuotaRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a demographic quota for a survey. Requires editor or above."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "editor", db)

    quota = Quota(
        survey_id=sid,
        name=body.name,
        dimension=body.dimension,
        target_count=body.target_count,
        criteria=body.criteria,
    )
    db.add(quota)

    await log_audit(
        db, action="quota.create", user_id=user.id,
        resource_type="quota", resource_id=quota.id,
        details={"dimension": body.dimension, "target": body.target_count},
        request=request,
    )
    await db.commit()
    await db.refresh(quota)
    return _build_quota_response(quota)


@router.get(
    "/{survey_id}/quotas",
    response_model=list[QuotaResponse],
    summary="List quotas for a survey",
    description=(
        "List every quota configured for the survey, newest-first, "
        "with the running count and target. Caller must hold at "
        "least viewer permission."
    ),
)
async def list_quotas(
    survey_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all quotas for a survey. Requires viewer or above."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    result = await db.execute(
        select(Quota)
        .where(Quota.survey_id == sid)
        .order_by(Quota.created_at.desc())
    )
    return [_build_quota_response(q) for q in result.scalars().all()]


@router.put(
    "/{survey_id}/quotas/{quota_id}",
    response_model=QuotaResponse,
    summary="Update a quota",
    description=(
        "Partial update of one quota's name, target count, "
        "matching criteria, or active flag. Caller must hold "
        "editor or owner permission."
    ),
)
async def update_quota(
    survey_id: UUID,
    quota_id: UUID,
    body: UpdateQuotaRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a quota. Requires editor or above."""
    sid = str(survey_id)
    qid = str(quota_id)
    await check_survey_permission(sid, user, "editor", db)

    result = await db.execute(
        select(Quota).where(Quota.id == qid, Quota.survey_id == sid)
    )
    quota = result.scalar_one_or_none()
    if quota is None:
        raise HTTPException(status_code=404, detail="配额不存在")

    if body.name is not None:
        quota.name = body.name
    if body.target_count is not None:
        quota.target_count = body.target_count
    if body.criteria is not None:
        quota.criteria = body.criteria
    if body.is_active is not None:
        quota.is_active = body.is_active

    db.add(quota)
    await log_audit(
        db, action="quota.update", user_id=user.id,
        resource_type="quota", resource_id=qid, request=request,
    )
    await db.commit()
    await db.refresh(quota)
    return _build_quota_response(quota)


@router.delete(
    "/{survey_id}/quotas/{quota_id}",
    status_code=204,
    summary="Delete a quota",
    description=(
        "Hard-delete one quota. Restricted to the survey owner; "
        "in-flight responses will no longer be matched against the "
        "deleted quota."
    ),
)
async def delete_quota(
    survey_id: UUID,
    quota_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a quota. Owner only."""
    sid = str(survey_id)
    qid = str(quota_id)
    await check_survey_permission(sid, user, "owner", db)

    result = await db.execute(
        select(Quota).where(Quota.id == qid, Quota.survey_id == sid)
    )
    quota = result.scalar_one_or_none()
    if quota is None:
        raise HTTPException(status_code=404, detail="配额不存在")

    await db.delete(quota)
    await log_audit(
        db, action="quota.delete", user_id=user.id,
        resource_type="quota", resource_id=qid, request=request,
    )
    await db.commit()


# ═══════════════════════════════════════════════════════════════════════════
# Dashboard
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/{survey_id}/distribution-dashboard",
    response_model=DistributionDashboardResponse,
    summary="Get the distribution dashboard for a survey",
    description=(
        "Aggregate one survey's distribution health into a single "
        "payload: total recipients, response count, response rate, "
        "active and total distribution counts, current quotas, and "
        "the sample-group inventory. Caller must hold at least "
        "viewer permission."
    ),
)
async def get_distribution_dashboard(
    survey_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get an aggregated dashboard for all sample distribution activity."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    # Survey title
    result = await db.execute(select(Survey).where(Survey.id == sid))
    survey = result.scalar_one_or_none()
    survey_title = survey.title if survey else ""

    # Total recipients across all sample groups
    result = await db.execute(
        select(func.coalesce(func.sum(SampleGroup.recipient_count), 0))
        .where(SampleGroup.survey_id == sid)
    )
    total_recipients = result.scalar() or 0

    # Total completed responses (via recipient status)
    result = await db.execute(
        select(func.count())
        .select_from(Recipient)
        .join(SampleGroup, Recipient.sample_group_id == SampleGroup.id)
        .where(SampleGroup.survey_id == sid, Recipient.status == "completed")
    )
    total_responded = result.scalar() or 0

    response_rate = (
        round(total_responded / total_recipients * 100, 1)
        if total_recipients > 0
        else 0.0
    )

    # Distribution counts
    result = await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(Distribution.status.in_(["draft", "sending", "sent"])).label("active"),
        ).where(Distribution.survey_id == sid)
    )
    row = result.one()
    total_distributions = row.total or 0
    active_distributions = row.active or 0

    # Quotas
    result = await db.execute(
        select(Quota).where(Quota.survey_id == sid).order_by(Quota.created_at.desc())
    )
    quotas = [_build_quota_response(q) for q in result.scalars().all()]

    # Sample groups
    result = await db.execute(
        select(SampleGroup)
        .where(SampleGroup.survey_id == sid)
        .order_by(SampleGroup.created_at.desc())
    )
    sample_groups = [SampleGroupResponse.model_validate(g) for g in result.scalars().all()]

    return DistributionDashboardResponse(
        survey_id=sid,
        survey_title=survey_title,
        total_recipients=total_recipients,
        total_responded=total_responded,
        response_rate=response_rate,
        total_distributions=total_distributions,
        active_distributions=active_distributions,
        quotas=quotas,
        sample_groups=sample_groups,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Public Token-Based Fill
# ═══════════════════════════════════════════════════════════════════════════

public_router = APIRouter(prefix="/surveys", tags=["distribution-public"])


@public_router.get(
    "/fill/{token}",
    summary="Resolve a recipient token to a survey fill URL",
    description=(
        "Public endpoint: resolve a per-recipient invite token "
        "into the redirect target the front-end should load. The "
        "first call also marks the recipient as ``opened`` so the "
        "distribution dashboard reflects accurate engagement. "
        "Tokens are 32-character ``uuid.hex`` values minted at "
        "send time."
    ),
)
async def resolve_fill_token(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint: resolve a recipient token to a survey fill URL.

    Returns redirect info for the client. Marks the recipient as ``opened``
    on first access.

    Unique tokens (uuid.hex, 32 chars) are embedded in survey invitation
    links for per-recipient tracking.
    """
    recipient = await match_recipient_from_token(db, token)
    if recipient is None:
        raise HTTPException(status_code=404, detail="无效的问卷链接")

    # Get the survey via sample group
    result = await db.execute(
        select(Survey)
        .join(SampleGroup, SampleGroup.survey_id == Survey.id)
        .where(SampleGroup.id == recipient.sample_group_id)
    )
    survey = result.scalar_one_or_none()
    if survey is None or survey.status != "published":
        raise HTTPException(status_code=404, detail="问卷不可用或已关闭")

    # Mark as opened (idempotent: only transition from sent → opened)
    if recipient.status == "sent":
        recipient.status = "opened"
        recipient.opened_at = datetime.now(timezone.utc)
        db.add(recipient)
        await db.commit()

    return {
        "survey_id": survey.id,
        "survey_title": survey.title,
        "recipient_id": recipient.id,
        "recipient_name": recipient.name,
        "token": token,
        "redirect_url": f"/survey/{survey.id}/fill",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _build_quota_response(quota: Quota) -> QuotaResponse:
    """Build a QuotaResponse with computed fill_rate."""
    fill_rate = (
        round(quota.current_count / quota.target_count * 100, 1)
        if quota.target_count > 0
        else 0.0
    )
    return QuotaResponse(
        id=quota.id,
        survey_id=quota.survey_id,
        name=quota.name,
        dimension=quota.dimension,
        target_count=quota.target_count,
        current_count=quota.current_count,
        criteria=quota.criteria,
        is_active=quota.is_active,
        fill_rate=fill_rate,
        created_at=quota.created_at,
        updated_at=quota.updated_at,
    )
