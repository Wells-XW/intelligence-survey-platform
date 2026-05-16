"""Pydantic schemas for Knowledge Base and Literature Search API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "results": [
                        {
                            "title": "Academic integrity among graduate students in China",
                            "authors": ["Wang, L.", "Liu, Y."],
                            "year": 2021,
                            "journal": "Journal of Academic Ethics",
                            "abstract": "We surveyed 612 graduate students…",
                            "doi": "10.1007/s10805-021-09412-7",
                            "url": "https://doi.org/10.1007/s10805-021-09412-7",
                            "source": "semantic_scholar",
                            "external_id": "S2:212f3b9c1e",
                            "keywords": ["academic integrity", "China"],
                        }
                    ],
                    "total_count": 184,
                    "source": "semantic_scholar",
                    "query": "academic integrity graduate students",
                    "cached": False,
                }
            ]
        }
    )


# ═══════════════════════════════════════════════════════════════════════════
# Saved References
# ═══════════════════════════════════════════════════════════════════════════

class SaveReferenceRequest(BaseModel):
    """Save (upsert) a literature reference to the user's library."""

    literature: LiteratureResult
    notes: Optional[str] = Field(default=None, max_length=2000)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "literature": {
                        "title": "Academic integrity among graduate students in China",
                        "authors": ["Wang, L.", "Liu, Y."],
                        "year": 2021,
                        "journal": "Journal of Academic Ethics",
                        "abstract": "We surveyed 612 graduate students…",
                        "doi": "10.1007/s10805-021-09412-7",
                        "url": "https://doi.org/10.1007/s10805-021-09412-7",
                        "source": "semantic_scholar",
                        "external_id": "S2:212f3b9c1e",
                        "keywords": ["academic integrity", "China"],
                    },
                    "notes": "Likely useful for the literature review chapter.",
                }
            ]
        }
    )


_SAVED_REFERENCE_EXAMPLE = {
    "id": "9f1e6c2a-4d2c-4a11-83b0-7384d9a84f3b",
    "title": "Academic integrity among graduate students in China",
    "authors": ["Wang, L.", "Liu, Y."],
    "year": 2021,
    "journal": "Journal of Academic Ethics",
    "abstract": "We surveyed 612 graduate students…",
    "doi": "10.1007/s10805-021-09412-7",
    "url": "https://doi.org/10.1007/s10805-021-09412-7",
    "source": "semantic_scholar",
    "external_id": "S2:212f3b9c1e",
    "keywords": ["academic integrity", "China"],
    "is_saved": True,
    "notes": "Likely useful for the literature review chapter.",
    "created_at": "2026-09-15T10:23:00Z",
}


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

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [_SAVED_REFERENCE_EXAMPLE]},
    )


class SavedReferenceListResponse(BaseModel):
    """Paginated list of saved references."""

    items: list[SavedReferenceResponse]
    total: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"items": [_SAVED_REFERENCE_EXAMPLE], "total": 1}
            ]
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "学术诚信简表-中文版（ACI-CN-2019）",
                    "discipline": "教育学",
                    "description": "面向中国大学生的简化学术诚信测量量表",
                    "items": [
                        {
                            "code": "Q1",
                            "text": "我能识别哪些行为构成学术不端。",
                            "reverse_scored": False,
                        },
                        {
                            "code": "Q2",
                            "text": "在压力下，偶尔抄袭是可以接受的。",
                            "reverse_scored": True,
                        },
                    ],
                    "cronbach_alpha": 0.86,
                    "language": "zh",
                }
            ]
        }
    )


_SCALE_RESPONSE_EXAMPLE = {
    "id": "scale_aci_zh_2019",
    "name": "学术诚信简表-中文版（ACI-CN-2019）",
    "discipline": "教育学",
    "description": "面向中国大学生的简化学术诚信测量量表",
    "items": [
        {
            "code": "Q1",
            "text": "我能识别哪些行为构成学术不端。",
            "reverse_scored": False,
        }
    ],
    "cronbach_alpha": 0.86,
    "cronbach_alpha_history": [
        {
            "value": 0.86,
            "sample_n": 612,
            "year": 2019,
            "citation": "Wang & Liu (2019)",
        }
    ],
    "citations": [
        {
            "title": "Academic integrity among graduate students in China",
            "authors": "Wang, L.; Liu, Y.",
            "year": 2021,
            "doi": "10.1007/s10805-021-09412-7",
        }
    ],
    "language": "zh",
    "source_type": "manual",
    "created_at": "2026-09-01T08:00:00Z",
    "updated_at": "2026-09-01T08:00:00Z",
}


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

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [_SCALE_RESPONSE_EXAMPLE]},
    )


class ScaleSearchResponse(BaseModel):
    """Paginated scale search results."""

    results: list[ScaleResponse]
    total_count: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"results": [_SCALE_RESPONSE_EXAMPLE], "total_count": 1}
            ]
        }
    )


class ScaleImportRequest(BaseModel):
    """Request to import scale items into a survey."""

    survey_id: str = Field(..., description="Target survey ID")
    position: str = Field(
        default="end", description="Insert position: start | end | after:<question_id>"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "position": "after:q3",
                }
            ]
        }
    )


class ScaleImportResponse(BaseModel):
    """Result of importing a scale into a survey."""

    survey_id: str
    items_added: int
    survey_json: dict

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "items_added": 5,
                    "survey_json": {"pages": [{"name": "page1", "elements": []}]},
                }
            ]
        }
    )


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

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "kb_pipl_consent_basics",
                    "title": "PIPL 知情同意条款撰写要点",
                    "category": "ethics",
                    "content": {
                        "markdown": (
                            "# 知情同意要点\n\n"
                            "1. 数据用途必须明确写出。\n"
                            "2. 列出可能的接收方。\n"
                        )
                    },
                    "tags": ["pipl", "consent"],
                    "language": "zh",
                    "created_at": "2026-09-01T08:00:00Z",
                }
            ]
        },
    )


class KnowledgeEntrySearchResponse(BaseModel):
    """Paginated knowledge entry search results."""

    results: list[KnowledgeEntryResponse]
    total_count: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "results": [
                        {
                            "id": "kb_pipl_consent_basics",
                            "title": "PIPL 知情同意条款撰写要点",
                            "category": "ethics",
                            "content": None,
                            "tags": ["pipl", "consent"],
                            "language": "zh",
                            "created_at": "2026-09-01T08:00:00Z",
                        }
                    ],
                    "total_count": 1,
                }
            ]
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "topic": "学术诚信",
                    "research_question": (
                        "硕博研究生对学术诚信制度的认知是否随导师指导频率而变化？"
                    ),
                    "include_literature": True,
                    "include_scales": True,
                }
            ]
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "literature_findings": [],
                    "related_scales": [_SCALE_RESPONSE_EXAMPLE],
                    "ai_summary": (
                        "已找到 1 个高相关量表（ACI-CN-2019）与 12 篇近 5 年文献。"
                        "建议优先复用已验证量表。"
                    ),
                    "scales_ai_extracted": None,
                    "model_used": "deepseek-chat",
                    "tokens_used": 2840,
                }
            ]
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "text": None,
                    "doi": "10.1007/s10805-021-09412-7",
                    "discipline": "教育学",
                }
            ]
        }
    )
