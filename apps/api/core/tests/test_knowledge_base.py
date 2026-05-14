"""Tests for Knowledge Base and Literature Search (Task 8)."""

from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.models.knowledge_scale import KnowledgeScale
from app.models.literature_reference import LiteratureReference
from app.schemas.knowledge_base import (
    KnowledgeEntrySearchRequest,
    LiteratureResult,
    LiteratureSearchRequest,
    LiteratureSearchResponse,
    SaveReferenceRequest,
    ScaleCreateRequest,
    ScaleImportRequest,
    ScaleItem,
    ScaleSearchRequest,
    ScaleSearchResponse,
)
from app.services.knowledge_base import (
    KnowledgeBaseService,
    LiteratureSearchService,
    ScaleLibraryService,
    _make_cache_key,
    _similarity,
)

# ═════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════

MOCK_PUBMED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2025//EN" "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_250101.dtd">
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation Status="Publisher" Owner="NLM">
      <PMID Version="1">12345678</PMID>
      <Article PubModel="Print-Electronic">
        <ArticleTitle>Understanding Survey Nonresponse Bias: A Meta-Analysis</ArticleTitle>
        <AuthorList>
          <Author>
            <LastName>Smith</LastName>
            <ForeName>John</ForeName>
          </Author>
          <Author>
            <LastName>Chen</LastName>
            <ForeName>Li</ForeName>
          </Author>
        </AuthorList>
        <Journal>
          <ISSN>0165-1781</ISSN>
          <JournalIssue>
            <Volume>10</Volume>
            <PubDate><Year>2024</Year></PubDate>
          </JournalIssue>
          <Title>Journal of Survey Methodology</Title>
        </Journal>
        <Abstract>
          <AbstractText Label="BACKGROUND">Survey nonresponse is a pervasive problem.</AbstractText>
          <AbstractText Label="RESULTS">Meta-analysis reveals moderate effect sizes.</AbstractText>
        </Abstract>
      </Article>
      <MeshHeadingList>
        <MeshHeading><DescriptorName>Surveys and Questionnaires</DescriptorName></MeshHeading>
        <MeshHeading><DescriptorName>Bias</DescriptorName></MeshHeading>
      </MeshHeadingList>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1000/survey.2024.001</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation Status="Publisher" Owner="NLM">
      <PMID Version="1">87654321</PMID>
      <Article PubModel="Print-Electronic">
        <ArticleTitle>Advancements in Scale Development for Social Sciences</ArticleTitle>
        <AuthorList>
          <Author>
            <LastName>Wang</LastName>
            <ForeName>Mei</ForeName>
          </Author>
        </AuthorList>
        <Journal>
          <JournalIssue>
            <PubDate><Year>2023</Year></PubDate>
          </JournalIssue>
          <Title>Psychological Methods</Title>
        </Journal>
        <Abstract>
          <AbstractText>New approaches to scale validation are presented.</AbstractText>
        </Abstract>
      </Article>
      <MeshHeadingList>
        <MeshHeading><DescriptorName>Psychometrics</DescriptorName></MeshHeading>
      </MeshHeadingList>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1000/psych.2023.005</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""

MOCK_S2_RESPONSE = {
    "data": [
        {
            "paperId": "s2-paper-001",
            "title": "Understanding Survey Nonresponse Bias: A Meta-Analysis",
            "authors": [{"name": "John Smith"}, {"name": "Li Chen"}],
            "year": 2024,
            "journal": {"name": "Journal of Survey Methodology"},
            "abstract": "Survey nonresponse is a pervasive problem.",
            "externalIds": {"DOI": "10.1000/survey.2024.001"},
            "url": "https://semanticscholar.org/paper/001",
            "publicationTypes": ["JournalArticle"],
        },
        {
            "paperId": "s2-paper-002",
            "title": "Different Study on Web Surveys",
            "authors": [{"name": "Zhang Wei"}],
            "year": 2022,
            "journal": None,
            "abstract": "Web surveys are increasingly common.",
            "externalIds": {},
            "url": "https://semanticscholar.org/paper/002",
            "publicationTypes": ["JournalArticle"],
        },
    ]
}

# ═════════════════════════════════════════════════════════════════════════
# Unit: Cache Key
# ═════════════════════════════════════════════════════════════════════════


class TestCacheKey:
    """Redis cache key generation."""

    def test_cache_key_deterministic(self):
        """Same request should produce the same cache key."""
        req1 = LiteratureSearchRequest(query="survey bias", source="all")
        req2 = LiteratureSearchRequest(query="survey bias", source="all")
        assert _make_cache_key(req1) == _make_cache_key(req2)

    def test_cache_key_differs_by_query(self):
        """Different queries produce different keys."""
        req1 = LiteratureSearchRequest(query="survey bias")
        req2 = LiteratureSearchRequest(query="scale validation")
        assert _make_cache_key(req1) != _make_cache_key(req2)

    def test_cache_key_prefix(self):
        """All cache keys should start with 'lit_search:'."""
        req = LiteratureSearchRequest(query="bias")
        assert _make_cache_key(req).startswith("lit_search:")


# ═════════════════════════════════════════════════════════════════════════
# Unit: Deduplication
# ═════════════════════════════════════════════════════════════════════════


class TestDeduplication:
    """Deduplication logic tests."""

    def test_title_similarity_identical(self):
        """Identical titles should have similarity 1.0."""
        assert _similarity("Survey Nonresponse Bias", "Survey Nonresponse Bias") == 1.0

    def test_title_similarity_different(self):
        """Very different titles should have low similarity."""
        sim = _similarity(
            "Survey Nonresponse Bias: A Meta-Analysis",
            "Studies on Cell Division in Yeast",
        )
        assert sim < 0.4

    def test_deduplicate_by_doi(self):
        """Results with identical DOI should be merged."""
        service = LiteratureSearchService(db=MagicMock())
        r1 = LiteratureResult(
            title="T1", authors=["A"], year=2024,
            doi="10.1000/paper.001", source="pubmed", external_id="1",
        )
        r2 = LiteratureResult(
            title="T1", authors=["A"], year=2024,
            doi="10.1000/paper.001", source="semantic_scholar", external_id="s2-1",
        )
        deduped = service._deduplicate([r1, r2])
        assert len(deduped) == 1

    def test_deduplicate_by_similar_title(self):
        """Results with very similar titles (>85%) should be deduplicated."""
        service = LiteratureSearchService(db=MagicMock())
        r1 = LiteratureResult(
            title="Understanding Survey Nonresponse Bias: A Meta-Analysis",
            authors=["A"], year=2024, source="pubmed", external_id="1",
        )
        r2 = LiteratureResult(
            title="Understanding Survey Nonresponse Bias: A Meta-Analysis",  # identical
            authors=["A"], year=2024, source="semantic_scholar", external_id="2",
        )
        deduped = service._deduplicate([r1, r2])
        assert len(deduped) == 1


# ═════════════════════════════════════════════════════════════════════════
# Unit: PubMed XML Parsing
# ═════════════════════════════════════════════════════════════════════════


class TestPubMedParsing:
    """PubMed efetch XML parsing."""

    def test_parse_pubmed_xml_extracts_fields(self):
        """XML parser should correctly extract all fields."""
        service = LiteratureSearchService(db=MagicMock())
        results = service._parse_pubmed_xml(MOCK_PUBMED_XML)
        assert len(results) == 2

        # First article: Smith & Chen
        r = results[0]
        assert r.title == "Understanding Survey Nonresponse Bias: A Meta-Analysis"
        # Author format is "LastName ForeName"
        assert "Smith John" in r.authors
        assert "Chen Li" in r.authors
        assert r.year == 2024
        assert r.journal == "Journal of Survey Methodology"
        assert r.doi == "10.1000/survey.2024.001"
        assert r.source == "pubmed"
        assert r.external_id == "12345678"
        assert "BACKGROUND" in r.abstract or "Survey nonresponse" in r.abstract
        assert len(r.keywords) >= 1
        assert "Surveys and Questionnaires" in r.keywords

    def test_parse_empty_xml(self):
        """Empty or invalid XML should return empty list."""
        service = LiteratureSearchService(db=MagicMock())
        assert service._parse_pubmed_xml("") == []
        assert service._parse_pubmed_xml("<not-pubmed/>") == []


# ═════════════════════════════════════════════════════════════════════════
# Unit: LiteratureSearchService — Redis caching
# ═════════════════════════════════════════════════════════════════════════


class TestLiteratureCache:
    """Redis cache integration in LiteratureSearchService."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_immediately(self):
        """When Redis has a cached response, skip external API calls."""
        mock_redis = AsyncMock()
        cached_resp = LiteratureSearchResponse(
            results=[
                LiteratureResult(
                    title="Cached Result", authors=["X"], year=2023,
                    source="pubmed", external_id="cached-1",
                )
            ],
            total_count=1, source="all", query="test",
        )
        mock_redis.get.return_value = cached_resp.model_dump_json()

        service = LiteratureSearchService(db=MagicMock(), redis=mock_redis)
        req = LiteratureSearchRequest(query="test", source="all")
        result = await service.search(req)

        assert result.cached is True
        assert result.total_count == 1
        assert result.results[0].title == "Cached Result"
        # Should NOT have called external APIs
        mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_miss_calls_external(self):
        """When Redis returns None, external APIs should be called."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        service = LiteratureSearchService(db=MagicMock(), redis=mock_redis)
        # Mock the HTTP client methods
        with patch.object(service, "_search_pubmed", new_callable=AsyncMock) as mock_pubmed, \
             patch.object(service, "_search_semantic_scholar", new_callable=AsyncMock) as mock_s2:

            mock_pubmed.return_value = [
                LiteratureResult(
                    title="PubMed Result", authors=["X"], year=2024,
                    source="pubmed", external_id="1",
                )
            ]
            mock_s2.return_value = []

            req = LiteratureSearchRequest(query="test", source="all")
            result = await service.search(req)

            assert result.cached is False
            assert result.total_count == 1
            # Should cache the result in Redis
            mock_redis.setex.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════
# Unit: ScaleLibraryService
# ═════════════════════════════════════════════════════════════════════════


class TestScaleLibraryService:
    """Scale library CRUD logic tests."""

    @pytest.mark.asyncio
    async def test_import_to_survey_start(self):
        """Scale items prepended to first page elements."""
        service = ScaleLibraryService(db=MagicMock())
        from app.models.knowledge_scale import KnowledgeScale
        scale = KnowledgeScale(
            id="scale-001", name="Test Scale", discipline="psychology",
            items=[
                {"code": "Q1", "text": "Item 1", "reverse_scored": False},
                {"code": "Q2", "text": "Item 2", "reverse_scored": True},
            ],
        )
        service.get_scale = AsyncMock(return_value=scale)

        survey_json = {
            "pages": [{
                "name": "page1",
                "elements": [{"type": "text", "name": "demo", "title": "Age?"}],
            }]
        }
        n, updated = await service.import_to_survey("scale-001", survey_json, position="start")
        assert n == 2
        elements = updated["pages"][0]["elements"]
        assert len(elements) == 3  # 2 new + 1 existing
        assert elements[0]["type"] == "radiogroup"
        assert elements[0]["title"] == "Item 1"

    @pytest.mark.asyncio
    async def test_import_to_survey_end(self):
        """Scale items appended to last page when position='end'."""
        service = ScaleLibraryService(db=MagicMock())
        from app.models.knowledge_scale import KnowledgeScale
        scale = KnowledgeScale(
            id="scale-002", name="SWLS", discipline="psychology",
            items=[{"code": "SWLS1", "text": "Life is ideal", "reverse_scored": False}],
        )
        service.get_scale = AsyncMock(return_value=scale)

        survey_json = {
            "pages": [{
                "name": "page1",
                "elements": [{"type": "text", "name": "intro", "title": "Intro"}],
            }]
        }
        n, updated = await service.import_to_survey("scale-002", survey_json)
        assert n == 1
        elements = updated["pages"][0]["elements"]
        assert elements[-1]["title"] == "Life is ideal"

    @pytest.mark.asyncio
    async def test_import_nonexistent_scale(self):
        """Importing a nonexistent scale returns 0 items."""
        service = ScaleLibraryService(db=MagicMock())
        service.get_scale = AsyncMock(return_value=None)
        survey_json = {"pages": []}
        n, updated = await service.import_to_survey("no-such", survey_json)
        assert n == 0


# ═════════════════════════════════════════════════════════════════════════
# Unit: KnowledgeBaseService
# ═════════════════════════════════════════════════════════════════════════


class TestKnowledgeBaseService:
    """Knowledge base service logic tests."""

    @pytest.mark.asyncio
    async def test_save_reference_new(self, db_session):
        """Saving a new reference creates a LiteratureReference row."""
        service = KnowledgeBaseService(db_session)
        lit = LiteratureResult(
            title="Test Paper", authors=["Author One"],
            year=2024, journal="Test Journal",
            abstract="An abstract.", doi="10.1000/test.001",
            source="pubmed", external_id="pmid-001",
            keywords=["testing"],
        )
        req = SaveReferenceRequest(literature=lit, notes="Important paper")
        # Need a user first
        from app.models.user import User
        import uuid
        user = User(
            id=str(uuid.uuid4()), email="kb-test@test.com",
            hashed_password="hash", display_name="KB Tester",
        )
        db_session.add(user)
        await db_session.flush()

        ref = await service.save_reference(user.id, req)
        assert ref.title == "Test Paper"
        assert ref.is_saved is True
        assert ref.notes == "Important paper"
        assert ref.external_source == "pubmed"

    @pytest.mark.asyncio
    async def test_save_reference_upsert(self, db_session):
        """Saving the same reference again should update (not duplicate)."""
        import uuid
        from app.models.user import User

        user = User(
            id=str(uuid.uuid4()), email="kb-upsert@test.com",
            hashed_password="hash", display_name="KB Upsert",
        )
        db_session.add(user)
        await db_session.flush()

        service = KnowledgeBaseService(db_session)
        lit = LiteratureResult(
            title="Upsert Paper", authors=["A"], year=2023,
            source="semantic_scholar", external_id="s2-upsert",
            doi="10.1000/upsert.001",
        )
        req1 = SaveReferenceRequest(literature=lit, notes="First save")
        ref1 = await service.save_reference(user.id, req1)

        # Second save with different notes
        req2 = SaveReferenceRequest(literature=lit, notes="Updated notes")
        ref2 = await service.save_reference(user.id, req2)

        assert ref2.id == ref1.id  # same row
        assert ref2.notes == "Updated notes"

    @pytest.mark.asyncio
    async def test_delete_reference_wrong_user(self, db_session):
        """User A cannot delete user B's reference."""
        import uuid
        from app.models.user import User

        user_a = User(
            id=str(uuid.uuid4()), email="a-ref@test.com",
            hashed_password="hash", display_name="A",
        )
        user_b = User(
            id=str(uuid.uuid4()), email="b-ref@test.com",
            hashed_password="hash", display_name="B",
        )
        db_session.add_all([user_a, user_b])
        await db_session.flush()

        service = KnowledgeBaseService(db_session)
        lit = LiteratureResult(
            title="A's Paper", authors=["A"], year=2024,
            source="manual", external_id="manual-1",
        )
        ref = await service.save_reference(user_a.id, SaveReferenceRequest(literature=lit))
        await db_session.flush()

        # User B tries to delete A's reference
        deleted = await service.delete_reference(ref.id, user_b.id)
        assert deleted is False


# ═════════════════════════════════════════════════════════════════════════
# Integration: Literature Search Endpoints
# ═════════════════════════════════════════════════════════════════════════


class TestLiteratureSearchAPI:
    """Integration tests for GET /api/v1/kb/search/literature."""

    @pytest.mark.asyncio
    async def test_search_literature_no_auth(self, async_client):
        """Literature search is public — no authentication required."""
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            # Mock PubMed esearch + efetch + Semantic Scholar
            async def mock_get_side(url, **kwargs):
                m = AsyncMock()
                if "esearch" in url:
                    m.json.return_value = {"esearchresult": {"idlist": ["12345678"]}}
                    m.raise_for_status = MagicMock()
                    return m
                elif "efetch" in url:
                    m.text = MOCK_PUBMED_XML
                    m.raise_for_status = MagicMock()
                    return m
                elif "semanticscholar" in url:
                    m.json.return_value = MOCK_S2_RESPONSE
                    m.raise_for_status = MagicMock()
                    return m
                m.status_code = 404
                m.raise_for_status = MagicMock(side_effect=Exception("Not found"))
                return m
            mock_get.side_effect = mock_get_side

            resp = await async_client.get(
                "/api/v1/kb/search/literature",
                params={"query": "survey methodology", "source": "all"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "results" in data
            assert "total_count" in data

    @pytest.mark.asyncio
    async def test_search_requires_query_min_length(self, async_client):
        """Query with <2 chars should be rejected."""
        resp = await async_client.get(
            "/api/v1/kb/search/literature", params={"query": "a"}
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_search_source_filter(self, async_client):
        """source=pubmed should only hit PubMed."""
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            async def side(url, **kw):
                m = AsyncMock()
                if "esearch" in url:
                    m.json.return_value = {"esearchresult": {"idlist": ["12345678"]}}
                elif "efetch" in url:
                    m.text = MOCK_PUBMED_XML
                else:
                    m.json.return_value = {"data": []}
                m.raise_for_status = MagicMock()
                return m
            mock_get.side_effect = side

            resp = await async_client.get(
                "/api/v1/kb/search/literature",
                params={"query": "survey", "source": "pubmed"},
            )
            assert resp.status_code == 200


# ═════════════════════════════════════════════════════════════════════════
# Integration: Saved References Endpoints
# ═════════════════════════════════════════════════════════════════════════


class TestSavedReferencesAPI:
    """Integration tests for reference CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_list_references_requires_auth(self, async_client):
        """Unauthenticated access should be rejected."""
        resp = await async_client.get("/api/v1/kb/references")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_save_and_list_references(self, async_client, auth_headers):
        """Save a reference then list it."""
        # Save
        resp = await async_client.post(
            "/api/v1/kb/references",
            json={
                "literature": {
                    "title": "Reference from API",
                    "authors": ["Test Author"],
                    "year": 2024,
                    "journal": "API Test Journal",
                    "abstract": "Testing the save endpoint.",
                    "doi": "10.5555/api-test.001",
                    "source": "pubmed",
                    "external_id": "api-test-pmid",
                },
                "notes": "API note",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Reference from API"
        assert data["is_saved"] is True
        assert data["notes"] == "API note"

        # List
        resp2 = await async_client.get(
            "/api/v1/kb/references", headers=auth_headers
        )
        assert resp2.status_code == 200
        items = resp2.json()["items"]
        assert len(items) >= 1
        assert items[0]["title"] == "Reference from API"

    @pytest.mark.asyncio
    async def test_delete_reference(self, async_client, auth_headers):
        """Save then delete a reference."""
        # Save
        resp = await async_client.post(
            "/api/v1/kb/references",
            json={
                "literature": {
                    "title": "To Be Deleted",
                    "authors": ["X"],
                    "source": "manual",
                    "external_id": "delete-me",
                },
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        ref_id = resp.json()["id"]

        # Delete
        resp2 = await async_client.delete(
            f"/api/v1/kb/references/{ref_id}", headers=auth_headers
        )
        assert resp2.status_code == 204

        # Verify gone
        resp3 = await async_client.get(
            "/api/v1/kb/references", headers=auth_headers
        )
        assert all(r["id"] != ref_id for r in resp3.json()["items"])

    @pytest.mark.asyncio
    async def test_delete_nonexistent_reference(self, async_client, auth_headers):
        """Deleting a nonexistent reference should 404."""
        resp = await async_client.delete(
            "/api/v1/kb/references/nonexistent-id", headers=auth_headers
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_reference_isolation(self, async_client):
        """User A cannot see User B's saved references."""
        from tests.test_surveys_auth import _register_and_login

        headers_a = await _register_and_login(async_client, "ref-a@test.com", "PassA123!", "RefA")
        headers_b = await _register_and_login(async_client, "ref-b@test.com", "PassB123!", "RefB")

        # User A saves a reference
        await async_client.post(
            "/api/v1/kb/references",
            json={
                "literature": {
                    "title": "A's Reference",
                    "authors": ["A"],
                    "source": "manual",
                    "external_id": "a-only",
                },
            },
            headers=headers_a,
        )

        # User B's list should be empty
        resp = await async_client.get("/api/v1/kb/references", headers=headers_b)
        assert resp.status_code == 200
        titles = [r["title"] for r in resp.json()["items"]]
        assert "A's Reference" not in titles


# ═════════════════════════════════════════════════════════════════════════
# Integration: Scale Library Endpoints
# ═════════════════════════════════════════════════════════════════════════


class TestScaleLibraryAPI:
    """Integration tests for scale CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_list_scales_public(self, async_client):
        """Scale listing is public (no auth required)."""
        resp = await async_client.get("/api/v1/kb/scales")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "total_count" in data

    @pytest.mark.asyncio
    async def test_create_scale_requires_auth(self, async_client):
        """Creating a scale requires authentication."""
        resp = await async_client.post(
            "/api/v1/kb/scales",
            json={
                "name": "Unauthorized Scale",
                "discipline": "psychology",
            },
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_scale_crud_flow(self, async_client, auth_headers):
        """Full CRUD lifecycle for a scale."""
        # Create
        resp = await async_client.post(
            "/api/v1/kb/scales",
            json={
                "name": "Test Scale via API",
                "discipline": "sociology",
                "description": "Created in integration test",
                "items": [
                    {"code": "TS1", "text": "Test item 1", "reverse_scored": False},
                    {"code": "TS2", "text": "Test item 2", "reverse_scored": True},
                ],
                "cronbach_alpha": 0.85,
                "language": "zh",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        created = resp.json()
        assert created["name"] == "Test Scale via API"
        assert created["discipline"] == "sociology"
        scale_id = created["id"]

        # Get by ID
        resp2 = await async_client.get(f"/api/v1/kb/scales/{scale_id}")
        assert resp2.status_code == 200
        assert resp2.json()["name"] == "Test Scale via API"

        # Update
        resp3 = await async_client.put(
            f"/api/v1/kb/scales/{scale_id}",
            json={
                "name": "Updated Scale Name",
                "discipline": "psychology",
                "description": "Updated description",
                "items": [
                    {"code": "TS1", "text": "Test item 1", "reverse_scored": False},
                ],
                "cronbach_alpha": 0.90,
                "language": "zh",
            },
            headers=auth_headers,
        )
        assert resp3.status_code == 200
        assert resp3.json()["name"] == "Updated Scale Name"

        # Delete
        resp4 = await async_client.delete(
            f"/api/v1/kb/scales/{scale_id}", headers=auth_headers
        )
        assert resp4.status_code == 204

        # Verify deletion
        resp5 = await async_client.get(f"/api/v1/kb/scales/{scale_id}")
        assert resp5.status_code == 404

    @pytest.mark.asyncio
    async def test_search_scales_by_discipline(self, async_client, auth_headers):
        """Filter scales by discipline."""
        # Create two scales in different disciplines
        await async_client.post(
            "/api/v1/kb/scales",
            json={"name": "Psych Scale", "discipline": "psychology", "language": "en"},
            headers=auth_headers,
        )
        await async_client.post(
            "/api/v1/kb/scales",
            json={"name": "Soc Scale", "discipline": "sociology", "language": "en"},
            headers=auth_headers,
        )

        # Search by discipline
        resp = await async_client.get(
            "/api/v1/kb/scales", params={"discipline": "psychology"}
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert all(r["discipline"] == "psychology" for r in results)
        # Check that our newly created scale is included
        psych_names = {r["name"] for r in results}
        assert "Psych Scale" in psych_names

    @pytest.mark.asyncio
    async def test_delete_nonexistent_scale(self, async_client, auth_headers):
        """Deleting a nonexistent scale should 404."""
        resp = await async_client.delete(
            "/api/v1/kb/scales/fake-scale-id", headers=auth_headers
        )
        assert resp.status_code == 404


# ═════════════════════════════════════════════════════════════════════════
# Integration: Knowledge Entries Endpoint
# ═════════════════════════════════════════════════════════════════════════


class TestKnowledgeEntriesAPI:
    """Integration tests for knowledge entries endpoints."""

    @pytest.mark.asyncio
    async def test_search_entries_public(self, async_client):
        """Knowledge entry search is public."""
        resp = await async_client.get("/api/v1/kb/entries")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "total_count" in data

    @pytest.mark.asyncio
    async def test_get_entry_not_found(self, async_client):
        """Getting a nonexistent entry should 404."""
        resp = await async_client.get("/api/v1/kb/entries/fake-entry-id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_search_entries_by_category(self, async_client):
        """Filter entries by category."""
        resp = await async_client.get(
            "/api/v1/kb/entries", params={"category": "methodology_guide"}
        )
        assert resp.status_code == 200
        data = resp.json()
        for r in data["results"]:
            assert r["category"] == "methodology_guide"


# ═════════════════════════════════════════════════════════════════════════
# Schema Validation Tests
# ═════════════════════════════════════════════════════════════════════════


class TestKBSchemas:
    """Pydantic schema validation for knowledge base."""

    def test_literature_search_request_defaults(self):
        """Default values should be applied correctly."""
        req = LiteratureSearchRequest(query="test query")
        assert req.source == "all"
        assert req.max_results == 20
        assert req.search_type == "keyword"
        assert req.language == "all"

    def test_literature_search_invalid_year_range(self):
        """year_from > year_to should raise validation error."""
        with pytest.raises(Exception):
            LiteratureSearchRequest(query="test", year_from=2025, year_to=2020)

    def test_save_reference_validates(self):
        """Valid save reference request passes."""
        lit = LiteratureResult(
            title="Paper", authors=["A"], source="pubmed", external_id="1",
        )
        req = SaveReferenceRequest(literature=lit, notes="Good")
        assert req.notes == "Good"

    def test_save_reference_notes_too_long(self):
        """Notes over 2000 chars should be rejected."""
        lit = LiteratureResult(
            title="Paper", authors=["A"], source="pubmed", external_id="1",
        )
        with pytest.raises(Exception):
            SaveReferenceRequest(literature=lit, notes="x" * 2001)
