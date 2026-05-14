"""Survey CRUD API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import Survey
from ...schemas.survey import (
    CreateSurveyRequest,
    SurveyListItem,
    SurveyResponse,
    UpdateSurveyRequest,
)

router = APIRouter(prefix="/surveys", tags=["surveys"])


@router.get("", response_model=list[SurveyListItem])
async def list_surveys(
    status: str | None = Query(default=None, description="Filter by status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List all surveys, ordered by most recently updated."""
    query = select(Survey).order_by(Survey.updated_at.desc())
    if status:
        query = query.where(Survey.status == status)
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    surveys = result.scalars().all()
    return [SurveyListItem.model_validate(s) for s in surveys]


@router.post("", response_model=SurveyResponse, status_code=201)
async def create_survey(
    body: CreateSurveyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new survey."""
    survey = Survey(
        title=body.title,
        description=body.description,
        json_content=body.json_content,
    )
    db.add(survey)
    await db.commit()
    await db.refresh(survey)
    return SurveyResponse.model_validate(survey)


@router.get("/{survey_id}", response_model=SurveyResponse)
async def get_survey(
    survey_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a survey by ID including full JSON content."""
    result = await db.execute(select(Survey).where(Survey.id == str(survey_id)))
    survey = result.scalar_one_or_none()
    if survey is None:
        raise HTTPException(status_code=404, detail="Survey not found")
    return SurveyResponse.model_validate(survey)


@router.put("/{survey_id}", response_model=SurveyResponse)
async def update_survey(
    survey_id: UUID,
    body: UpdateSurveyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update a survey. Only fields provided will be updated."""
    result = await db.execute(select(Survey).where(Survey.id == str(survey_id)))
    survey = result.scalar_one_or_none()
    if survey is None:
        raise HTTPException(status_code=404, detail="Survey not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(survey, key, value)
    survey.version += 1

    await db.commit()
    await db.refresh(survey)
    return SurveyResponse.model_validate(survey)


@router.delete("/{survey_id}", status_code=204)
async def delete_survey(
    survey_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a survey and all associated data."""
    result = await db.execute(select(Survey).where(Survey.id == str(survey_id)))
    survey = result.scalar_one_or_none()
    if survey is None:
        raise HTTPException(status_code=404, detail="Survey not found")

    await db.delete(survey)
    await db.commit()
