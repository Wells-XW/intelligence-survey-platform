"""Pydantic schemas for Knowledge Base and Literature Search API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# ═══════════════════════════════════════════════════════════════════════════
# Literature Search
# ═══════════════════════════════════════════════════════════════════════════

class LiteratureSearchRequest(BaseModel):
    """Search parameters for academic literature."""

    query: str = Field(..., min_length=2, max_length=500, description="搜索关键词")
    source: str = Field(
        default="all", description="数据源: pubmed | semantic_scholar | all"
    )
    search_type: str = Field(
        default="keyword",
        description="搜索类型: keyword | author | doi | topic",
    )
    year_from: Optional[int] = Field(default=None, ge=1900, le=2030)
    year_to: Optional[int] = Field(default=None, ge=1900, le=2030)
    max_results: int = Field(default=20, ge=5, le=50)
    language: str = Field(default="all", description="all | zh | en")

    @model_validator(mode="after")
    def validate_year_range(self) -> "LiteratureSearchRequest":
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("year_from must be <= year_to")
        return self


class LiteratureResult(BaseModel):
    """A single literature search result from an external source."""

    title: str
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    journal: Optional[str] = None
    abstract: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    source: str  # pubmed | semantic_scholar | cnki_web
    external_id: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)


class LiteratureSearchResponse(BaseModel):
    """Paginated, multi-source literature search response."""

    results: list[LiteratureResult]
    total_count: int
    source: str
    query: str
    cached: bool = False


# ═══════════════════════════════════════════════════════════════════════════
# Saved References
# ═══════════════════════════════════════════════════════════════════════════

class SaveReferenceRequest(BaseModel):
    """Save (upsert) a literature reference to the user's library."""

    literature: LiteratureResult
    notes: Optional[str] = Field(default=None, max_length=2000)


class SavedReferenceResponse(BaseModel):
    """A user's saved literature reference."""

    id: str
    title: str
    authors: Optional[list] = None
    year: Optional[int] = None
    journal: Optional[str] = None
    abstract: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    source: str
    external_id: Optional[str] = None
    keywords: Optional[list] = None
    is_saved: bool = True
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SavedReferenceListResponse(BaseModel):
    """Paginated list of saved references."""

    items: list[SavedReferenceResponse]
    total: int


# ═══════════════════════════════════════════════════════════════════════════
# Knowledge Scales
# ═══════════════════════════════════════════════════════════════════════════

class ScaleItem(BaseModel):
    """A single item within a measurement scale."""

    code: str
    text: str
    reverse_scored: bool = False


class ScaleCronbachHistory(BaseModel):
    """A historical Cronbach's alpha data point."""

    value: float
    sample_n: int
    year: int
    citation: str


class ScaleCitation(BaseModel):
    """A citation for the scale."""

    title: str
    authors: str
    year: int
    doi: Optional[str] = None


class ScaleSearchRequest(BaseModel):
    """Search/filter parameters for the scale library."""

    query: Optional[str] = Field(default=None, max_length=200)
    discipline: Optional[str] = None
    language: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ScaleCreateRequest(BaseModel):
    """Create or update a measurement scale."""

    name: str = Field(..., min_length=1, max_length=500)
    discipline: str
    description: Optional[str] = None
    items: Optional[list[ScaleItem]] = None
    cronbach_alpha: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    cronbach_alpha_history: Optional[list[ScaleCronbachHistory]] = None
    citations: Optional[list[ScaleCitation]] = None
    language: str = "zh"


class ScaleResponse(BaseModel):
    """Full scale detail response."""

    id: str
    name: str
    discipline: str
    description: Optional[str] = None
    items: Optional[list] = None  # list[ScaleItem] raw from JSONB
    cronbach_alpha: Optional[float] = None
    cronbach_alpha_history: Optional[list] = None
    citations: Optional[list] = None
    language: str = "zh"
    source_type: str = "manual"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScaleSearchResponse(BaseModel):
    """Paginated scale search results."""

    results: list[ScaleResponse]
    total_count: int


class ScaleImportRequest(BaseModel):
    """Request to import scale items into a survey."""

    survey_id: str = Field(..., description="Target survey ID")
    position: str = Field(
        default="end", description="Insert position: start | end | after:<question_id>"
    )


class ScaleImportResponse(BaseModel):
    """Result of importing a scale into a survey."""

    survey_id: str
    items_added: int
    survey_json: dict


# ═══════════════════════════════════════════════════════════════════════════
# Knowledge Entries
# ═══════════════════════════════════════════════════════════════════════════

class KnowledgeEntrySearchRequest(BaseModel):
    """Search/filter knowledge base entries."""

    query: Optional[str] = Field(default=None, max_length=200)
    category: Optional[str] = None
    language: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class KnowledgeEntryResponse(BaseModel):
    """A knowledge base entry."""

    id: str
    title: str
    category: str
    content: Optional[dict] = None
    tags: Optional[list] = None
    language: str = "zh"
    created_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeEntrySearchResponse(BaseModel):
    """Paginated knowledge entry search results."""

    results: list[KnowledgeEntryResponse]
    total_count: int


# ═══════════════════════════════════════════════════════════════════════════
# AI-Assisted Search
# ═══════════════════════════════════════════════════════════════════════════

class AiAssistedSearchRequest(BaseModel):
    """AI-enhanced search combining literature + scales."""

    topic: str = Field(..., min_length=1, max_length=500, description="研究主题")
    research_question: Optional[str] = Field(
        default=None, max_length=500, description="研究问题"
    )
    include_literature: bool = True
    include_scales: bool = True


class AiExtractedScale(BaseModel):
    """AI-extracted scale items from literature."""

    name: str
    items: list[ScaleItem]


class AiAssistedSearchResponse(BaseModel):
    """Result of AI-assisted knowledge base search."""

    literature_findings: list[LiteratureResult] = Field(default_factory=list)
    related_scales: list[ScaleResponse] = Field(default_factory=list)
    ai_summary: str = ""
    scales_ai_extracted: Optional[list[AiExtractedScale]] = None
    model_used: str = ""
    tokens_used: int = 0


# ═══════════════════════════════════════════════════════════════════════════
# Scale Extraction
# ═══════════════════════════════════════════════════════════════════════════

class ScaleExtractRequest(BaseModel):
    """AI-powered scale extraction from a paper abstract or DOI."""

    text: Optional[str] = Field(
        default=None, max_length=5000, description="Paper abstract or text"
    )
    doi: Optional[str] = Field(default=None, description="DOI to fetch and extract from")
    discipline: str = Field(default="psychology", description="Target discipline hint")
