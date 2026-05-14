"""Knowledge Base services: literature search, scale library, knowledge entries.

Provides three service classes that follow the existing pattern from
``services/ai_generation.py``:

* ``LiteratureSearchService`` — unified search across PubMed, Semantic
  Scholar, and CNKI (web fallback), with Redis caching and deduplication.
* ``ScaleLibraryService`` — CRUD for validated measurement scales plus
  import-into-survey functionality.
* ``KnowledgeBaseService`` — user's saved references, methodology guides,
  and AI-assisted cross-search.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Optional
from xml.etree import ElementTree

import httpx
from redis.asyncio import Redis
from sqlalchemy import String, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.knowledge_entry import KnowledgeEntry
from ..models.knowledge_scale import KnowledgeScale
from ..models.literature_reference import LiteratureReference
from ..schemas.knowledge_base import (
    AiAssistedSearchRequest,
    AiAssistedSearchResponse,
    AiExtractedScale,
    KnowledgeEntrySearchRequest,
    KnowledgeEntrySearchResponse,
    LiteratureResult,
    LiteratureSearchRequest,
    LiteratureSearchResponse,
    SaveReferenceRequest,
    SavedReferenceListResponse,
    SavedReferenceResponse,
    ScaleCreateRequest,
    ScaleImportRequest,
    ScaleImportResponse,
    ScaleSearchRequest,
    ScaleSearchResponse,
    ScaleResponse,
)

logger = logging.getLogger(__name__)

# ── helpers ────────────────────────────────────────────────────────────────

def _make_cache_key(req: LiteratureSearchRequest) -> str:
    raw = f"{req.query}|{req.source}|{req.search_type}|{req.year_from}|{req.year_to}|{req.max_results}"
    return f"lit_search:{hashlib.md5(raw.encode()).hexdigest()}"


def _similarity(a: str, b: str) -> float:
    """Title similarity ratio (0-1) for deduplication."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _chunk_pmids(pmids: list[str], size: int = 50) -> list[list[str]]:
    """Chunk PMID list for efetch (max ~50 IDs per request)."""
    return [pmids[i : i + size] for i in range(0, len(pmids), size)]


# ── LiteratureSearchService ────────────────────────────────────────────────

class LiteratureSearchService:
    """Unified search across academic literature databases.

    Supports PubMed (Entrez E-utilities), Semantic Scholar (public API),
    and CNKI (best-effort web scrape fallback).  Caches results in Redis.
    """

    def __init__(self, db: AsyncSession, redis: Optional[Redis] = None):
        self.db = db
        self.redis = redis
        self._http = httpx.AsyncClient(timeout=30.0)

    # ── public API ────────────────────────────────────────────────────

    async def search(self, req: LiteratureSearchRequest) -> LiteratureSearchResponse:
        """Run a literature search across enabled sources."""

        # Redis cache check
        if self.redis:
            cache_key = _make_cache_key(req)
            cached = await self.redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                resp = LiteratureSearchResponse(**data)
                resp.cached = True
                return resp

        # Choose sources
        sources: list[str] = []
        if req.source in ("pubmed", "all"):
            sources.append("pubmed")
        if req.source in ("semantic_scholar", "all"):
            sources.append("semantic_scholar")

        if not sources:
            sources = ["pubmed", "semantic_scholar"]

        # Parallel fetch
        tasks = []
        if "pubmed" in sources:
            tasks.append(self._search_pubmed(req))
        if "semantic_scholar" in sources:
            tasks.append(self._search_semantic_scholar(req))

        results_lists = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: list[LiteratureResult] = []
        for r in results_lists:
            if isinstance(r, Exception):
                logger.warning("Literature search source failed: %s", r)
            else:
                all_results.extend(r)

        # Deduplicate and sort
        all_results = self._deduplicate(all_results)
        all_results.sort(key=lambda x: x.year or 0, reverse=True)
        all_results = all_results[: req.max_results]

        resp = LiteratureSearchResponse(
            results=all_results,
            total_count=len(all_results),
            source=req.source,
            query=req.query,
        )

        # Cache in Redis
        if self.redis:
            await self.redis.setex(
                _make_cache_key(req),
                settings.literature_cache_ttl,
                resp.model_dump_json(),
            )

        return resp

    # ── PubMed ─────────────────────────────────────────────────────────

    async def _search_pubmed(
        self, req: LiteratureSearchRequest
    ) -> list[LiteratureResult]:
        """Search PubMed via Entrez E-utilities."""
        base = settings.pubmed_base_url
        api_key = settings.pubmed_api_key
        params: dict = {"db": "pubmed", "retmax": str(req.max_results), "retmode": "json"}

        # Build query
        query_parts = [req.query]
        if req.year_from:
            query_parts.append(f"{req.year_from}[dp]")
        if req.year_to:
            query_parts.append(f"{req.year_to}[dp]")
        params["term"] = " AND ".join(query_parts)
        if api_key:
            params["api_key"] = api_key

        # Step 1: esearch -> PMID list
        esearch_url = f"{base}/esearch.fcgi"
        resp = await self._http.get(esearch_url, params=params)
        resp.raise_for_status()
        data = resp.json()
        pmids = data.get("esearchresult", {}).get("idlist", [])
        if not pmids:
            return []

        # Step 2: efetch -> article details
        articles = []
        for chunk in _chunk_pmids(pmids):
            efetch_url = f"{base}/efetch.fcgi"
            efetch_params = {
                "db": "pubmed",
                "id": ",".join(chunk),
                "retmode": "xml",
            }
            if api_key:
                efetch_params["api_key"] = api_key
            r = await self._http.get(efetch_url, params=efetch_params)
            r.raise_for_status()
            articles.extend(self._parse_pubmed_xml(r.text))
        return articles

    def _parse_pubmed_xml(self, xml_text: str) -> list[LiteratureResult]:
        """Parse PubMed efetch XML into LiteratureResult list."""
        results: list[LiteratureResult] = []
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            return results

        for article in root.findall(".//PubmedArticle"):
            try:
                med = article.find(".//MedlineCitation")
                if med is None:
                    continue
                art = med.find(".//Article")
                if art is None:
                    continue

                # Title
                title_el = art.find(".//ArticleTitle")
                title = title_el.text.strip() if title_el is not None and title_el.text else ""

                # Authors
                authors: list[str] = []
                for auth in art.findall(".//Author"):
                    ln = auth.findtext("LastName", "")
                    fn = auth.findtext("ForeName", "")
                    name = f"{ln} {fn}".strip()
                    if name:
                        authors.append(name)

                # Journal
                journal_el = art.find(".//Journal/Title")
                journal = journal_el.text.strip() if journal_el is not None and journal_el.text else None

                # Year
                year_el = art.find(".//Journal/JournalIssue/PubDate/Year")
                year = int(year_el.text) if year_el is not None and year_el.text else None

                # Abstract
                ab_parts = []
                for ab in art.findall(".//Abstract/AbstractText"):
                    label = ab.get("Label", "")
                    txt = ab.text or ""
                    if label:
                        ab_parts.append(f"{label}: {txt}")
                    else:
                        ab_parts.append(txt)
                abstract = " ".join(ab_parts) if ab_parts else None

                # DOI
                doi_el = article.find(".//ArticleId[@IdType='doi']")
                doi = doi_el.text if doi_el is not None else None

                # PMID
                pmid_el = med.findtext(".//PMID", "")

                # Keywords (MeSH)
                keywords: list[str] = []
                for mh in med.findall(".//MeshHeading/DescriptorName"):
                    if mh.text:
                        keywords.append(mh.text)

                if title:
                    results.append(
                        LiteratureResult(
                            title=title,
                            authors=authors,
                            year=year,
                            journal=journal,
                            abstract=abstract,
                            doi=doi,
                            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid_el}/" if pmid_el else None,
                            source="pubmed",
                            external_id=pmid_el or None,
                            keywords=keywords,
                        )
                    )
            except Exception:
                logger.debug("Failed to parse a PubMed article", exc_info=True)
        return results

    # ── Semantic Scholar ───────────────────────────────────────────────

    async def _search_semantic_scholar(
        self, req: LiteratureSearchRequest
    ) -> list[LiteratureResult]:
        """Search Semantic Scholar public API."""
        base = settings.semantic_scholar_base_url
        headers: dict = {}
        if settings.semantic_scholar_api_key:
            headers["x-api-key"] = settings.semantic_scholar_api_key

        params = {
            "query": req.query,
            "limit": min(req.max_results, 100),
            "fields": "title,authors,year,journal,abstract,externalIds,url,publicationTypes",
        }
        if req.year_from:
            params["year"] = f"{req.year_from}-" + (str(req.year_to) if req.year_to else "")

        url = f"{base}/paper/search"
        resp = await self._http.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        results: list[LiteratureResult] = []
        for paper in data.get("data", []):
            try:
                authors = [a.get("name", "") for a in paper.get("authors", [])]
                ext = paper.get("externalIds", {}) or {}
                results.append(
                    LiteratureResult(
                        title=paper.get("title", ""),
                        authors=authors,
                        year=paper.get("year"),
                        journal=paper.get("journal", {}).get("name") if isinstance(paper.get("journal"), dict) else None,
                        abstract=paper.get("abstract"),
                        doi=ext.get("DOI"),
                        url=paper.get("url"),
                        source="semantic_scholar",
                        external_id=paper.get("paperId"),
                        keywords=[],
                    )
                )
            except Exception:
                logger.debug("Failed to parse Semantic Scholar paper", exc_info=True)
        return results

    # ── dedup ──────────────────────────────────────────────────────────

    def _deduplicate(self, results: list[LiteratureResult]) -> list[LiteratureResult]:
        """Remove duplicate results by DOI first, then title similarity."""
        seen_dois: set[str] = set()
        deduped: list[LiteratureResult] = []

        for r in results:
            # DOI exact match
            if r.doi and r.doi.lower() in seen_dois:
                continue
            # Title similarity check
            is_dup = False
            for existing in deduped:
                if _similarity(r.title, existing.title) > 0.85:
                    is_dup = True
                    # Merge: prefer the one with more metadata
                    if (r.abstract and not existing.abstract) or (
                        r.doi and not existing.doi
                    ):
                        existing.abstract = r.abstract or existing.abstract
                        existing.doi = r.doi or existing.doi
                    break
            if not is_dup:
                if r.doi:
                    seen_dois.add(r.doi.lower())
                deduped.append(r)

        return deduped

    async def close(self) -> None:
        await self._http.aclose()


# ── ScaleLibraryService ────────────────────────────────────────────────────

class ScaleLibraryService:
    """CRUD and search for validated academic measurement scales."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def search_scales(
        self, req: ScaleSearchRequest
    ) -> ScaleSearchResponse:
        q = select(KnowledgeScale)
        count_q = select(func.count(KnowledgeScale.id))

        if req.query:
            like = f"%{req.query}%"
            q = q.where(
                (KnowledgeScale.name.ilike(like))
                | (KnowledgeScale.description.ilike(like))
            )
            count_q = count_q.where(
                (KnowledgeScale.name.ilike(like))
                | (KnowledgeScale.description.ilike(like))
            )
        if req.discipline:
            q = q.where(KnowledgeScale.discipline == req.discipline)
            count_q = count_q.where(KnowledgeScale.discipline == req.discipline)
        if req.language:
            q = q.where(KnowledgeScale.language == req.language)
            count_q = count_q.where(KnowledgeScale.language == req.language)

        total = (await self.db.execute(count_q)).scalar() or 0
        rows = (await self.db.execute(q.limit(req.limit).offset(req.offset))).scalars().all()

        return ScaleSearchResponse(
            results=[ScaleResponse.model_validate(r) for r in rows],
            total_count=total,
        )

    async def get_scale(self, scale_id: str) -> Optional[KnowledgeScale]:
        result = await self.db.execute(
            select(KnowledgeScale).where(KnowledgeScale.id == scale_id)
        )
        return result.scalar_one_or_none()

    async def create_scale(
        self, data: ScaleCreateRequest, user_id: Optional[str] = None
    ) -> KnowledgeScale:
        scale = KnowledgeScale(
            name=data.name,
            discipline=data.discipline,
            description=data.description,
            items=[i.model_dump() for i in data.items] if data.items else None,
            cronbach_alpha=data.cronbach_alpha,
            cronbach_alpha_history=(
                [h.model_dump() for h in data.cronbach_alpha_history]
                if data.cronbach_alpha_history
                else None
            ),
            citations=(
                [c.model_dump() for c in data.citations]
                if data.citations
                else None
            ),
            language=data.language,
            created_by=user_id,
        )
        self.db.add(scale)
        await self.db.flush()
        return scale

    async def update_scale(
        self, scale_id: str, data: ScaleCreateRequest
    ) -> Optional[KnowledgeScale]:
        scale = await self.get_scale(scale_id)
        if not scale:
            return None
        scale.name = data.name
        scale.discipline = data.discipline
        scale.description = data.description
        scale.items = [i.model_dump() for i in data.items] if data.items else None
        scale.cronbach_alpha = data.cronbach_alpha
        scale.cronbach_alpha_history = (
            [h.model_dump() for h in data.cronbach_alpha_history]
            if data.cronbach_alpha_history
            else None
        )
        scale.citations = (
            [c.model_dump() for c in data.citations] if data.citations else None
        )
        scale.language = data.language
        scale.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return scale

    async def delete_scale(self, scale_id: str) -> bool:
        scale = await self.get_scale(scale_id)
        if not scale:
            return False
        await self.db.delete(scale)
        await self.db.flush()
        return True

    async def import_to_survey(
        self,
        scale_id: str,
        survey_json: dict,
        position: str = "end",
    ) -> tuple[int, dict]:
        """Transform scale items into SurveyJS JSON and inject into survey."""
        scale = await self.get_scale(scale_id)
        if not scale or not scale.items:
            return 0, survey_json

        pages = survey_json.get("pages", [])
        if not pages:
            pages = [{"name": "page1", "elements": []}]

        # Build SurveyJS-compatible elements from scale items
        new_elements = []
        for item in scale.items:
            el = {
                "type": "radiogroup",
                "name": item.get("code", f"scale_{scale_id[:8]}_{len(new_elements)}"),
                "title": item.get("text", ""),
                "choices": [
                    {"value": i, "text": str(i)}
                    for i in range(1, 6)  # default 5-point Likert
                ],
            }
            new_elements.append(el)

        # Inject into survey at the specified position
        if position == "start":
            pages[0]["elements"] = new_elements + pages[0].get("elements", [])
        elif position.startswith("after:"):
            target_qid = position[6:]
            for page in pages:
                for idx, el in enumerate(page.get("elements", [])):
                    if el.get("name") == target_qid:
                        page["elements"][idx + 1 : idx + 1] = new_elements
                        break
        else:  # "end" default
            pages[-1]["elements"] = pages[-1].get("elements", []) + new_elements

        survey_json["pages"] = pages
        return len(new_elements), survey_json


# ── KnowledgeBaseService ───────────────────────────────────────────────────

class KnowledgeBaseService:
    """User's saved references, methodology guides, and AI-assisted search."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── saved references ───────────────────────────────────────────────

    async def save_reference(
        self, user_id: str, req: SaveReferenceRequest
    ) -> LiteratureReference:
        lit = req.literature
        # Upsert: check if already exists
        result = await self.db.execute(
            select(LiteratureReference).where(
                LiteratureReference.user_id == user_id,
                LiteratureReference.external_source == lit.source,
                LiteratureReference.external_id == lit.external_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.is_saved = True
            existing.notes = req.notes or existing.notes
            await self.db.flush()
            return existing

        ref = LiteratureReference(
            user_id=user_id,
            external_source=lit.source,
            external_id=lit.external_id,
            title=lit.title,
            authors=lit.authors,
            year=lit.year,
            journal=lit.journal,
            abstract=lit.abstract,
            doi=lit.doi,
            url=lit.url,
            keywords=lit.keywords,
            is_saved=True,
            notes=req.notes,
        )
        self.db.add(ref)
        await self.db.flush()
        return ref

    async def get_saved_references(
        self, user_id: str, limit: int = 20, offset: int = 0
    ) -> SavedReferenceListResponse:
        q = (
            select(LiteratureReference)
            .where(
                LiteratureReference.user_id == user_id,
                LiteratureReference.is_saved == True,
            )
            .order_by(LiteratureReference.created_at.desc())
        )
        count_q = (
            select(func.count(LiteratureReference.id))
            .where(
                LiteratureReference.user_id == user_id,
                LiteratureReference.is_saved == True,
            )
        )

        total = (await self.db.execute(count_q)).scalar() or 0
        rows = (await self.db.execute(q.limit(limit).offset(offset))).scalars().all()

        return SavedReferenceListResponse(
            items=[SavedReferenceResponse.model_validate(r) for r in rows],
            total=total,
        )

    async def delete_reference(self, ref_id: str, user_id: str) -> bool:
        result = await self.db.execute(
            select(LiteratureReference).where(
                LiteratureReference.id == ref_id,
                LiteratureReference.user_id == user_id,
            )
        )
        ref = result.scalar_one_or_none()
        if not ref:
            return False
        await self.db.delete(ref)
        await self.db.flush()
        return True

    # ── entries ────────────────────────────────────────────────────────

    async def search_entries(
        self, req: KnowledgeEntrySearchRequest
    ) -> KnowledgeEntrySearchResponse:
        q = select(KnowledgeEntry).where(KnowledgeEntry.is_published == True)
        count_q = (
            select(func.count(KnowledgeEntry.id))
            .where(KnowledgeEntry.is_published == True)
        )

        if req.query:
            like = f"%{req.query}%"
            q = q.where(
                (KnowledgeEntry.title.ilike(like))
                | (KnowledgeEntry.tags.cast(String).ilike(like))
            )
            count_q = count_q.where(
                (KnowledgeEntry.title.ilike(like))
                | (KnowledgeEntry.tags.cast(String).ilike(like))
            )
        if req.category:
            q = q.where(KnowledgeEntry.category == req.category)
            count_q = count_q.where(KnowledgeEntry.category == req.category)
        if req.language:
            q = q.where(KnowledgeEntry.language == req.language)
            count_q = count_q.where(KnowledgeEntry.language == req.language)

        total = (await self.db.execute(count_q)).scalar() or 0
        rows = (await self.db.execute(q.limit(req.limit).offset(req.offset))).scalars().all()

        from ..schemas.knowledge_base import KnowledgeEntryResponse
        return KnowledgeEntrySearchResponse(
            results=[KnowledgeEntryResponse.model_validate(r) for r in rows],
            total_count=total,
        )

    async def get_entry(self, entry_id: str) -> Optional[KnowledgeEntry]:
        result = await self.db.execute(
            select(KnowledgeEntry).where(
                KnowledgeEntry.id == entry_id,
                KnowledgeEntry.is_published == True,
            )
        )
        return result.scalar_one_or_none()

    # ── AI-assisted search ─────────────────────────────────────────────

    async def ai_assisted_search(
        self, req: AiAssistedSearchRequest, user_id: str
    ) -> AiAssistedSearchResponse:
        """Use AI to expand search terms and find related literature + scales."""
        from ..core.ai_router import execute_ai_call

        lit_service = LiteratureSearchService(self.db)
        scale_service = ScaleLibraryService(self.db)

        system_prompt = (
            "你是一个学术研究方法论专家。用户提供了研究主题，请帮助识别：\n"
            "1. 核心概念和构念 (constructs)\n"
            "2. 该领域常用的测量量表\n"
            "3. 相关的关键词用于文献检索\n"
            "4. 一个简短的方法论建议摘要\n\n"
            "请用 JSON 格式回复：\n"
            '{"constructs": ["构念1"], "suggested_scales": ["量表1"], '
            '"search_terms": ["术语1"], "summary": "中文研究建议摘要"}'
        )

        user_prompt = f"研究主题：{req.topic}"
        if req.research_question:
            user_prompt += f"\n研究问题：{req.research_question}"

        # AI call
        result, _ = await execute_ai_call(
            task_category="literature_search",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=1500,
        )

        ai_data = {}
        try:
            content = result.text
            # Extract JSON from code blocks if present
            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                ai_data = json.loads(json_match.group())
        except (json.JSONDecodeError, AttributeError):
            logger.warning("Failed to parse AI-assisted search JSON")

        # Use AI-identified terms for parallel searches
        search_terms = ai_data.get("search_terms", [req.topic])
        if req.topic not in search_terms:
            search_terms.insert(0, req.topic)

        lit_req = LiteratureSearchRequest(
            query=search_terms[0],  # primary term
            source="all",
            max_results=10,
        )
        scale_req = ScaleSearchRequest(limit=10, offset=0)

        if ai_data.get("suggested_scales"):
            scale_req.query = ai_data["suggested_scales"][0]

        lit_resp, scale_resp = await asyncio.gather(
            lit_service.search(lit_req),
            scale_service.search_scales(scale_req),
        )

        return AiAssistedSearchResponse(
            literature_findings=lit_resp.results if req.include_literature else [],
            related_scales=scale_resp.results if req.include_scales else [],
            ai_summary=ai_data.get("summary", "AI 分析未生成摘要。"),
            model_used=result.model,
            tokens_used=result.total_tokens,
        )


# ── Module-level convenience functions ─────────────────────────────────────

def get_literature_service(
    db: AsyncSession, redis: Optional[Redis] = None
) -> LiteratureSearchService:
    """Create a LiteratureSearchService bound to the given session."""
    return LiteratureSearchService(db, redis)


def get_scale_service(db: AsyncSession) -> ScaleLibraryService:
    """Create a ScaleLibraryService bound to the given session."""
    return ScaleLibraryService(db)


def get_kb_service(db: AsyncSession) -> KnowledgeBaseService:
    """Create a KnowledgeBaseService bound to the given session."""
    return KnowledgeBaseService(db)
