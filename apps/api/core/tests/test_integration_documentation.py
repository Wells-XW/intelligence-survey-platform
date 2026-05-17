"""Task 18.2 — Documentation route integration test.

Validates that /api/v1/openapi.json, /docs, /redoc, and the integration
guide are all reachable and that internal /health is excluded from the
published OpenAPI schema.

Validates: Requirements 1.1, 1.2, 1.3, 1.5, 1.6, 1.7
"""

import pytest


@pytest.mark.asyncio
async def test_openapi_json_is_valid_3_x(async_client):
    """OpenAPI 3.x JSON is served at /api/v1/openapi.json with both auth schemes."""
    r = await async_client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema.get("openapi", "").startswith("3.")
    assert schema.get("paths"), "OpenAPI schema must expose at least one path"
    components = schema.get("components", {})
    security_schemes = components.get("securitySchemes", {})
    assert "BearerAuth" in security_schemes
    assert "ApiKeyAuth" in security_schemes


@pytest.mark.asyncio
async def test_swagger_ui_renders(async_client):
    """Swagger UI is served at /api/v1/docs as HTML."""
    r = await async_client.get("/api/v1/docs")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "swagger" in r.text.lower()


@pytest.mark.asyncio
async def test_redoc_renders(async_client):
    """ReDoc is served at /api/v1/redoc as HTML."""
    r = await async_client.get("/api/v1/redoc")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "redoc" in r.text.lower()


@pytest.mark.asyncio
async def test_integration_guide_is_reachable(async_client):
    """The integration usage guide is served as text/markdown."""
    r = await async_client.get("/api/v1/integration-guide/")
    assert r.status_code == 200
    assert "text/markdown" in r.headers.get("content-type", "")
    assert "Integration Guide" in r.text


@pytest.mark.asyncio
async def test_health_route_excluded_from_openapi(async_client):
    """The /health route is excluded from the published OpenAPI schema."""
    r = await async_client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    paths = r.json().get("paths", {})
    assert "/api/v1/health" not in paths
    assert "/health" not in paths
