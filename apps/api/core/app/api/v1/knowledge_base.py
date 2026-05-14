"""Knowledge Base API endpoints — literature search, scales, references, entries."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.audit import log_audit
from ...core.deps import (
    check_survey_permission,
    get_current_user,
    get_optional_user,
    get_redis,
)
from ...database import get_db
from ...models.knowledge_scale import KnowledgeScale
from ...models.survey import Survey
from ...models.user import User
from ...schemas.knowledge_base import (
    AiAssistedSearchRequest,
    AiAssistedSearchResponse,
    KnowledgeEntrySearchRequest,
    KnowledgeEntrySearchResponse,
    LiteratureSearchRequest,
    LiteratureSearchResponse,
    SaveReferenceRequest,
    SavedReferenceListResponse,
    SavedReferenceResponse,
    ScaleCreateRequest,
    ScaleExtractRequest,
    ScaleImportRequest,
    ScaleImportResponse,
    ScaleResponse,
    ScaleSearchRequest,
    ScaleSearchResponse,
)
from ...services.knowledge_base import (
    KnowledgeBaseService,
    LiteratureSearchService,
    ScaleLibraryService,
)

router = APIRouter(prefix="/kb", tags=["knowledge-base"])

# ── helper ─────────────────────────────────────────────────────────────────

async def _get_kb_service(db: AsyncSession = Depends(get_db)) -> KnowledgeBaseService:
    return KnowledgeBaseService(db)


async def _get_scale_service(
    db: AsyncSession = Depends(get_db),
) -> ScaleLibraryService:
    return ScaleLibraryService(db)


async def _get_lit_service(
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> LiteratureSearchService:
    return LiteratureSearchService(db, redis)


# ═══════════════════════════════════════════════════════════════════════════
# Literature Search
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/search/literature", response_model=LiteratureSearchResponse)
async def search_literature(
    query: str = Query(..., min_length=2, max_length=500),
    source: str = Query(default="all"),
    search_type: str = Query(default="keyword"),
    year_from: Optional[int] = Query(default=None),
    year_to: Optional[int] = Query(default=None),
    max_results: int = Query(default=20, ge=5, le=50),
    service: LiteratureSearchService = Depends(_get_lit_service),
):
    """Search academic literature across PubMed and Semantic Scholar.

    Supports keyword, author, DOI, and topic searches.  Results are
    deduplicated and cached in Redis for 1 hour.
    """
    req = LiteratureSearchRequest(
        query=query,
        source=source,
        search_type=search_type,
        year_from=year_from,
        year_to=year_to,
        max_results=max_results,
    )
    return await service.search(req)


# ═══════════════════════════════════════════════════════════════════════════
# Saved References
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/references", response_model=SavedReferenceListResponse)
async def list_saved_references(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    service: KnowledgeBaseService = Depends(_get_kb_service),
):
    """List the current user's saved literature references."""
    return await service.get_saved_references(user.id, limit, offset)


@router.post("/references", response_model=SavedReferenceResponse, status_code=201)
async def save_reference(
    data: SaveReferenceRequest,
    request: Request,
    user: User = Depends(get_current_user),
    service: KnowledgeBaseService = Depends(_get_kb_service),
    db: AsyncSession = Depends(get_db),
):
    """Save (bookmark) a literature reference.  Upserts on duplicate."""
    ref = await service.save_reference(user.id, data)
    await db.commit()
    await log_audit(
        db=db,
        action="save_reference",
        user_id=user.id,
        resource_type="literature_reference",
        resource_id=ref.id,
        request=request,
    )
    return SavedReferenceResponse.model_validate(ref)


@router.delete("/references/{ref_id}", status_code=204)
async def delete_reference(
    ref_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    service: KnowledgeBaseService = Depends(_get_kb_service),
    db: AsyncSession = Depends(get_db),
):
    """Remove a saved literature reference."""
    deleted = await service.delete_reference(ref_id, user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="参考文献不存在")
    await db.commit()
    await log_audit(
        db=db,
        action="delete_reference",
        user_id=user.id,
        resource_type="literature_reference",
        resource_id=ref_id,
        request=request,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Knowledge Scales
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/search/scales", response_model=ScaleSearchResponse)
async def search_scales(
    query: Optional[str] = Query(default=None),
    discipline: Optional[str] = Query(default=None),
    language: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: ScaleLibraryService = Depends(_get_scale_service),
):
    """Search the measurement scale library."""
    req = ScaleSearchRequest(
        query=query, discipline=discipline, language=language, limit=limit, offset=offset
    )
    return await service.search_scales(req)


@router.get("/scales", response_model=ScaleSearchResponse)
async def list_scales(
    discipline: Optional[str] = Query(default=None),
    language: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: ScaleLibraryService = Depends(_get_scale_service),
):
    """Browse all scales (public endpoint)."""
    req = ScaleSearchRequest(discipline=discipline, language=language, limit=limit, offset=offset)
    return await service.search_scales(req)


@router.get("/scales/{scale_id}", response_model=ScaleResponse)
async def get_scale(
    scale_id: str,
    service: ScaleLibraryService = Depends(_get_scale_service),
):
    """Get a single scale with full item details."""
    scale = await service.get_scale(scale_id)
    if not scale:
        raise HTTPException(status_code=404, detail="量表不存在")
    return ScaleResponse.model_validate(scale)


@router.post("/scales", response_model=ScaleResponse, status_code=201)
async def create_scale(
    data: ScaleCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    service: ScaleLibraryService = Depends(_get_scale_service),
    db: AsyncSession = Depends(get_db),
):
    """Create a new measurement scale (authenticated)."""
    scale = await service.create_scale(data, user.id)
    await db.commit()
    await log_audit(
        db=db,
        action="create_scale",
        user_id=user.id,
        resource_type="knowledge_scale",
        resource_id=scale.id,
        request=request,
    )
    return ScaleResponse.model_validate(scale)


@router.put("/scales/{scale_id}", response_model=ScaleResponse)
async def update_scale(
    scale_id: str,
    data: ScaleCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    service: ScaleLibraryService = Depends(_get_scale_service),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing scale."""
    scale = await service.update_scale(scale_id, data)
    if not scale:
        raise HTTPException(status_code=404, detail="量表不存在")
    await db.commit()
    await log_audit(
        db=db,
        action="update_scale",
        user_id=user.id,
        resource_type="knowledge_scale",
        resource_id=scale_id,
        request=request,
    )
    return ScaleResponse.model_validate(scale)


@router.delete("/scales/{scale_id}", status_code=204)
async def delete_scale(
    scale_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    service: ScaleLibraryService = Depends(_get_scale_service),
    db: AsyncSession = Depends(get_db),
):
    """Delete a scale."""
    deleted = await service.delete_scale(scale_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="量表不存在")
    await db.commit()
    await log_audit(
        db=db,
        action="delete_scale",
        user_id=user.id,
        resource_type="knowledge_scale",
        resource_id=scale_id,
        request=request,
    )


@router.post("/scales/{scale_id}/import", response_model=ScaleImportResponse)
async def import_scale_to_survey(
    scale_id: str,
    data: ScaleImportRequest,
    request: Request,
    user: User = Depends(get_current_user),
    service: ScaleLibraryService = Depends(_get_scale_service),
    db: AsyncSession = Depends(get_db),
):
    """Import a scale's items into a survey."""
    # Verify survey access
    await check_survey_permission(data.survey_id, user, "editor", db)

    # Load survey
    result = await db.execute(select(Survey).where(Survey.id == data.survey_id))
    survey = result.scalar_one_or_none()
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")

    items_added, updated_json = await service.import_to_survey(
        scale_id,
        survey.json_content,
        position=data.position,
    )
    if items_added == 0:
        raise HTTPException(status_code=404, detail="量表不存在或无题项")

    survey.json_content = updated_json
    survey.version += 1  # bump version on structural change
    await db.commit()

    await log_audit(
        db=db,
        action="import_scale",
        user_id=user.id,
        resource_type="survey",
        resource_id=data.survey_id,
        details={"scale_id": scale_id, "items_added": items_added},
        request=request,
    )

    return ScaleImportResponse(
        survey_id=data.survey_id,
        items_added=items_added,
        survey_json=updated_json,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Scale Extraction (AI-powered)
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/scales/extract", response_model=ScaleResponse, status_code=201)
async def extract_scale_from_text(
    data: ScaleExtractRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AI-powered: extract scale items from paper abstract or DOI.

    Uses the existing AI pipeline to identify structured measurement
    scales within academic text.  The extracted scale is saved to the
    library and returned.
    """
    from ...core.ai_router import execute_ai_call

    text = data.text or ""
    if data.doi and not text:
        # Try fetching from Semantic Scholar
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"https://api.semanticscholar.org/graph/v1/paper/DOI:{data.doi}",
                params={"fields": "title,abstract"},
            )
            if resp.status_code == 200:
                paper = resp.json()
                text = paper.get("abstract", "") or ""
                if not text:
                    raise HTTPException(status_code=422, detail="无法获取该 DOI 的摘要")

    if not text:
        raise HTTPException(status_code=400, detail="请提供文本或 DOI")

    system_prompt = (
        "你是一个学术研究方法论专家。请从提供的学术文本中提取结构化量表信息。\n"
        "返回 JSON 格式：\n"
        '{"name": "量表名称", "description": "简短描述", '
        '"items": [{"code": "Q1", "text": "题项文字", "reverse_scored": false}], '
        '"estimated_alpha": 0.85, "citation": {"title": "论文标题", "authors": "作者", "year": 2024}}'
    )

    result, _ = await execute_ai_call(
        task_category="item_refinement",
        system_prompt=system_prompt,
        user_prompt=f"提取以下文本中的量表：\n\n{text[:4000]}",
        temperature=0.2,
        max_tokens=2000,
    )

    import json as _json, re as _re
    match = _re.search(r"\{[\s\S]*\}", result.text)
    if not match:
        raise HTTPException(status_code=422, detail="AI 未能从文本中提取到量表")

    extracted = _json.loads(match.group())
    scale = KnowledgeScale(
        name=extracted.get("name", "AI 提取量表"),
        discipline=data.discipline,
        description=extracted.get("description", ""),
        items=[{"code": i.get("code"), "text": i.get("text"), "reverse_scored": i.get("reverse_scored", False)}
               for i in extracted.get("items", [])],
        cronbach_alpha=extracted.get("estimated_alpha"),
        citations=[extracted.get("citation")] if extracted.get("citation") else None,
        language="zh" if any("一" <= c <= "鿿" for c in text[:100]) else "en",
        source_type="api",
        created_by=user.id,
    )
    db.add(scale)
    await db.commit()

    await log_audit(
        db=db,
        action="extract_scale",
        user_id=user.id,
        resource_type="knowledge_scale",
        resource_id=scale.id,
        request=request,
    )

    return ScaleResponse.model_validate(scale)


# ═══════════════════════════════════════════════════════════════════════════
# Knowledge Entries
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/entries", response_model=KnowledgeEntrySearchResponse)
async def search_entries(
    query: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    language: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: KnowledgeBaseService = Depends(_get_kb_service),
):
    """Search published knowledge base entries (public)."""
    req = KnowledgeEntrySearchRequest(
        query=query, category=category, language=language, limit=limit, offset=offset
    )
    return await service.search_entries(req)


@router.get("/entries/{entry_id}")
async def get_entry(
    entry_id: str,
    service: KnowledgeBaseService = Depends(_get_kb_service),
):
    """Get a single knowledge base entry by ID."""
    from ...schemas.knowledge_base import KnowledgeEntryResponse as EResp

    entry = await service.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="条目不存在")
    return EResp.model_validate(entry)


# ═══════════════════════════════════════════════════════════════════════════
# AI-Assisted Search
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/search/ai-assisted", response_model=AiAssistedSearchResponse)
async def ai_assisted_search(
    data: AiAssistedSearchRequest,
    user: User = Depends(get_current_user),
    service: KnowledgeBaseService = Depends(_get_kb_service),
):
    """AI-enhanced search: expand search terms and find related literature
    and scales in parallel."""
    return await service.ai_assisted_search(data, user.id)
