"""Survey response collection & retrieval API.

Response submission is public (no auth required) to support
anonymous survey respondents. Retrieval requires authentication.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.audit import log_audit
from ...core.deps import check_survey_permission, get_current_user
from ...database import get_db
from ...models.survey_response import SurveyResponse
from ...models.user import User
from ...schemas.response import (
    SubmitResponseRequest,
    SurveyResponseListItem,
    SurveyResponseOut,
)
from ...services.webhook_emitter import (
    emit_webhook_event,
    enqueue_webhook_deliveries,
)

router = APIRouter(prefix="/surveys", tags=["responses"])


@router.post(
    "/{survey_id}/responses",
    response_model=SurveyResponseOut,
    status_code=201,
    summary="Submit a survey response",
    description=(
        "Submit one survey response. The endpoint is unauthenticated "
        "to support anonymous respondents; the survey must be in "
        "``published`` status. The ``metadata`` payload must include "
        "``pipl_consent: true`` per PIPL Article 18, and the "
        "client's IP is stored with the last octet zeroed for "
        "anonymization. Emits ``response.created`` and (when "
        "``is_complete=true``) ``response.completed`` webhook events."
    ),
)
async def submit_response(
    survey_id: UUID,
    body: SubmitResponseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Submit a survey response. No authentication required.

    PIPL Compliance:
    - ``body.metadata`` MUST include ``"pipl_consent": true``.
    - IP address is anonymized (last octet zeroed) before storage.
    """
    sid = str(survey_id)

    # Verify survey exists and is published
    from ...models.survey import Survey

    result = await db.execute(select(Survey).where(Survey.id == sid))
    survey = result.scalar_one_or_none()
    if survey is None:
        raise HTTPException(status_code=404, detail="问卷不存在")
    if survey.status != "published":
        raise HTTPException(status_code=403, detail="该问卷暂未开放填写")

    # PIPL consent check
    if not body.metadata.get("pipl_consent"):
        raise HTTPException(
            status_code=400,
            detail="根据《个人信息保护法》第18条，提交前需确认知情同意 (pipl_consent)",
        )

    # Anonymize IP (last octet zeroed for PIPL compliance)
    client_ip = request.client.host if request.client else "unknown"
    ip_parts = client_ip.rsplit(".", 1)
    safe_ip = f"{ip_parts[0]}.0" if len(ip_parts) == 2 else client_ip

    metadata = {
        **body.metadata,
        "ip_address": safe_ip,
        "user_agent": request.headers.get("User-Agent", ""),
    }

    response = SurveyResponse(
        survey_id=sid,
        respondent_id=body.respondent_id,
        answers=body.answers,
        metadata_json=metadata,
        is_complete=body.is_complete,
    )
    db.add(response)
    await db.flush()
    await db.refresh(response)

    # Emit domain events for webhook fan-out. Deliveries are inserted
    # in the same transaction so a downstream rollback removes them
    # cleanly; Celery enqueue happens only after commit succeeds.
    submitted_at_iso = (
        response.submitted_at.isoformat() if response.submitted_at else None
    )
    delivery_ids = await emit_webhook_event(
        db,
        event_type="response.created",
        survey_id=sid,
        payload={
            "survey_id": sid,
            "response_id": str(response.id),
            "submitted_at": submitted_at_iso,
        },
    )
    if body.is_complete:
        delivery_ids += await emit_webhook_event(
            db,
            event_type="response.completed",
            survey_id=sid,
            payload={
                "survey_id": sid,
                "response_id": str(response.id),
                "submitted_at": submitted_at_iso,
            },
        )

    await db.commit()
    await db.refresh(response)
    enqueue_webhook_deliveries(delivery_ids)

    # If respondent_id corresponds to a Recipient, update recipient status
    # and increment matching quotas (sample distribution integration)
    if body.respondent_id and body.is_complete:
        from ...models.recipient import Recipient
        from ...services.sample_service import update_quota_on_response

        r_result = await db.execute(
            select(Recipient).where(Recipient.id == body.respondent_id)
        )
        recipient = r_result.scalar_one_or_none()
        if recipient and recipient.status != "completed":
            recipient.status = "completed"
            recipient.completed_at = datetime.now(timezone.utc)
            db.add(recipient)
            # Update matching quotas; this may emit quota.reached events.
            quota_delivery_ids = await update_quota_on_response(
                db, body.respondent_id, sid
            )
            await db.commit()
            enqueue_webhook_deliveries(quota_delivery_ids)

    return SurveyResponseOut.model_validate(response)


@router.get(
    "/{survey_id}/responses",
    response_model=list[SurveyResponseListItem],
    summary="List responses for a survey",
    description=(
        "Return responses for one survey, newest-first, paginated by "
        "``offset`` and ``limit`` (page size capped at 1000). Caller "
        "must hold at least viewer permission on the survey."
    ),
)
async def list_responses(
    survey_id: UUID,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List responses for a survey. Requires at least viewer permission."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    result = await db.execute(
        select(SurveyResponse)
        .where(SurveyResponse.survey_id == sid)
        .order_by(SurveyResponse.submitted_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = result.scalars().all()
    return [SurveyResponseListItem.from_orm_row(r) for r in rows]


@router.get(
    "/{survey_id}/responses/{response_id}",
    response_model=SurveyResponseOut,
    summary="Get a single response",
    description=(
        "Return one response by id, including the full ``answers`` "
        "payload and submission metadata. Caller must hold at least "
        "viewer permission on the parent survey."
    ),
)
async def get_response(
    survey_id: UUID,
    response_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single response by ID. Requires at least viewer permission."""
    sid = str(survey_id)
    rid = str(response_id)
    await check_survey_permission(sid, user, "viewer", db)

    result = await db.execute(
        select(SurveyResponse).where(
            SurveyResponse.id == rid,
            SurveyResponse.survey_id == sid,
        )
    )
    response = result.scalar_one_or_none()
    if response is None:
        raise HTTPException(status_code=404, detail="回复不存在")

    return SurveyResponseOut.model_validate(response)


@router.delete(
    "/{survey_id}/responses",
    status_code=204,
    summary="Delete all responses for a survey",
    description=(
        "Bulk-delete every response row for one survey. Restricted "
        "to the survey owner because the operation is destructive "
        "and irreversible. Emits a single ``responses.bulk_delete`` "
        "audit row carrying the deleted-count."
    ),
)
async def delete_all_responses(
    survey_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete all responses for a survey. Owner only."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "owner", db)

    # Count before delete
    count_result = await db.execute(
        select(func.count()).select_from(SurveyResponse).where(
            SurveyResponse.survey_id == sid
        )
    )
    count = count_result.scalar() or 0

    await db.execute(
        SurveyResponse.__table__.delete().where(SurveyResponse.survey_id == sid)
    )

    await log_audit(
        db,
        action="responses.bulk_delete",
        user_id=user.id,
        resource_type="survey",
        resource_id=sid,
        details={"deleted_count": count},
        request=request,
    )

    await db.commit()


@router.get(
    "/{survey_id}/responses/export",
    summary="Export responses as CSV or XLSX",
    description=(
        "Stream survey responses as a downloadable CSV file. The "
        "``format`` query parameter is reserved for future XLSX "
        "support; both values currently emit CSV with a flattened "
        "header (``response_id``, ``respondent_id``, ``submitted_at``, "
        "``is_complete``, plus one column per question). For "
        "asynchronous multi-format exports use the "
        "``/api/v1/exports`` endpoint family instead."
    ),
)
async def export_responses(
    survey_id: UUID,
    format: str = Query(default="csv", pattern="^(csv|xlsx)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export survey responses as CSV or Excel.

    Requires at least viewer permission.
    """
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    # Fetch all responses
    result = await db.execute(
        select(SurveyResponse)
        .where(SurveyResponse.survey_id == sid)
        .order_by(SurveyResponse.submitted_at.asc())
    )
    rows = result.scalars().all()

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)

        # Header: metadata columns + flattened answer columns
        if rows:
            # Collect all unique answer keys
            all_keys: list[str] = []
            seen_keys: set[str] = set()
            for row in rows:
                for key in row.answers:
                    if key not in seen_keys:
                        all_keys.append(key)
                        seen_keys.add(key)

            headers = ["response_id", "respondent_id", "submitted_at", "is_complete"] + all_keys
            writer.writerow(headers)

            for row in rows:
                base = [
                    row.id,
                    row.respondent_id or "",
                    row.submitted_at.isoformat(),
                    str(row.is_complete),
                ]
                answer_vals = [row.answers.get(key, "") for key in all_keys]
                writer.writerow(base + answer_vals)

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="survey_{sid[:8]}_responses.csv"'
            },
        )

    # XLSX export — simple CSV for MVP with .xlsx extension hint
    # Full XLSX with openpyxl would be added in a future iteration
    output = io.StringIO()
    writer = csv.writer(output)
    if rows:
        all_keys: list[str] = []
        seen_keys: set[str] = set()
        for row in rows:
            for key in row.answers:
                if key not in seen_keys:
                    all_keys.append(key)
                    seen_keys.add(key)
        headers = ["response_id", "respondent_id", "submitted_at", "is_complete"] + all_keys
        writer.writerow(headers)
        for row in rows:
            base = [
                row.id,
                row.respondent_id or "",
                row.submitted_at.isoformat(),
                str(row.is_complete),
            ]
            answer_vals = [row.answers.get(key, "") for key in all_keys]
            writer.writerow(base + answer_vals)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="survey_{sid[:8]}_responses.csv"'
        },
    )
