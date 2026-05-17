"""Property test P25: Universal internal-route exclusion.

Per design §Property 25 (Requirement 1.7) every route flagged with
``include_in_schema=False`` must be absent from the rendered OpenAPI
schema's ``paths`` mapping. The current internal-only candidates are
``app/api/v1/health.py`` and any future debug routers; FastAPI
honours the per-route flag automatically, but the test pins the
guarantee so a regression (e.g. accidentally exposing ``/health``
through a router-level decorator change) surfaces immediately.

Scope choice
------------

This is an introspective enumeration over :attr:`app.main.app.routes`,
not a Hypothesis property test in the ``@given`` sense. The "input
space" is the finite set of internal-flagged routes.

Validates: Requirements 1.7
"""

from __future__ import annotations

from typing import List, Set

import pytest
from fastapi.routing import APIRoute

from app.main import app


def _internal_route_paths() -> List[str]:
    """Collect the paths of every route with ``include_in_schema=False``.

    Returned as a list (not a set) so the assertion message can show
    the routes in their declaration order if the property fails.
    Duplicates are kept on purpose: a duplicate would itself indicate
    a misconfigured router.
    """
    return [
        r.path
        for r in app.routes
        if isinstance(r, APIRoute) and not r.include_in_schema
    ]


# Feature: api-platform-export, Property 25: Universal internal-route exclusion
# Validates: Requirements 1.7
def test_p25_internal_routes_excluded_from_openapi_paths() -> None:
    """Every internal route is absent from the published schema's ``paths``.

    Renders the OpenAPI schema fresh (clearing the FastAPI app's
    cached schema first so the test runs against current metadata),
    intersects the schema's ``paths`` keys against the internal-route
    paths, and asserts the intersection is empty. A non-empty
    intersection means an internal-only route is leaking into the
    published documentation surface.
    """
    internal_paths = _internal_route_paths()
    assert internal_paths, (
        "expected at least one internal route (e.g. /api/v1/health) "
        "marked include_in_schema=False; the test surface is empty"
    )

    # Force a fresh schema render — earlier tests may have cached one.
    app.openapi_schema = None
    schema = app.openapi()
    published: Set[str] = set(schema.get("paths", {}).keys())

    leaked = sorted(set(internal_paths) & published)
    if leaked:
        pytest.fail(
            "Internal routes leaked into the published OpenAPI schema:\n"
            + "\n".join(f"  {p}" for p in leaked),
            pytrace=False,
        )


# Feature: api-platform-export, Property 25: Universal internal-route exclusion
# Validates: Requirements 1.7
def test_p25_health_route_is_internal() -> None:
    """The ``/health`` operational probe is flagged internal.

    Belt-and-suspenders sanity check: confirms the canonical
    internal-only route documented in design §Component 12 is
    actually marked. A future refactor that splits the health
    endpoint into a separate router must keep the flag set.
    """
    health_routes = [
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.path == "/api/v1/health"
    ]
    assert health_routes, (
        "expected /api/v1/health to be registered on the FastAPI app"
    )
    for route in health_routes:
        assert route.include_in_schema is False, (
            f"/api/v1/health route is published in the schema "
            f"(include_in_schema={route.include_in_schema})"
        )
