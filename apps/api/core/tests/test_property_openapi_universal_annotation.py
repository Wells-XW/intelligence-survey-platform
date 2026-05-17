"""Property test P24: Universal documentation annotation.

Per design §Property 24 (Requirement 1.4) every route with
``include_in_schema=True`` must carry a non-empty ``summary``, a
non-empty ``description``, and at least one example response. The
property is enforced at the introspection layer rather than at the
HTTP layer because every input is a deterministic property of the
FastAPI ``app`` object, and rendering the schema once is much cheaper
than spinning up a test client per route.

Scope choice
------------

This module is **not** a Hypothesis property test in the
``@given``-driven sense. The "input space" is the finite set of
:class:`fastapi.routing.APIRoute` instances on
:attr:`app.main.app.routes`; enumerating them directly gives the same
guarantee as a randomized property test would, but with deterministic
output and no shrinking overhead. We use plain pytest assertions and
report every offending route in a single failure message so a Task
16.2-style backfill can prioritize the offenders.

Validates: Requirements 1.4
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest
from fastapi.routing import APIRoute

from app.main import app


def _resolve_ref(
    ref: str, components: Dict[str, Any]
) -> Dict[str, Any]:
    """Resolve a single ``$ref`` link into the referenced component schema.

    OpenAPI ``$ref`` values look like ``#/components/schemas/Foo``;
    we split off the trailing component name and look it up on the
    components-schemas map. Returns an empty dict when the ref
    cannot be resolved so the caller's ``.get`` traversal
    short-circuits cleanly.
    """
    name = ref.rsplit("/", 1)[-1]
    return components.get(name, {})


def _schema_carries_example(
    schema: Dict[str, Any], components: Dict[str, Any]
) -> bool:
    """Return True if the schema (possibly via ``$ref`` or ``items``) has examples.

    Walks one level of ``$ref`` resolution and one level of array
    ``items`` indirection. Every schema FastAPI generates from a
    Pydantic model with ``json_schema_extra={"examples": [...]}``
    surfaces here through ``components.schemas[<Model>].examples``.
    """
    if not isinstance(schema, dict):
        return False
    if "example" in schema or "examples" in schema:
        return True
    ref = schema.get("$ref")
    if ref:
        return _schema_carries_example(_resolve_ref(ref, components), components)
    items = schema.get("items")
    if isinstance(items, dict):
        return _schema_carries_example(items, components)
    return False


def _operation_has_example(
    operation: Dict[str, Any], components: Dict[str, Any]
) -> bool:
    """Return True if any response on the operation surfaces an example.

    Acceptance rules per design §Property 24, with a relaxation for
    body-less responses:

    * A ``204 No Content`` response counts as compliant because it
      carries no body.
    * A response with ``content`` whose media-type entry carries an
      ``example`` or ``examples`` key counts.
    * A response whose schema (directly or via ``$ref`` / ``items``)
      carries an ``example`` or ``examples`` key counts.
    """
    for code, body in (operation.get("responses") or {}).items():
        if code == "204":
            return True
        content = body.get("content") or {}
        if not content:
            # Bodyless non-204 responses (e.g. a 404 with description
            # only) do not carry an example by design; skip without
            # claiming compliance.
            continue
        for mtbody in content.values():
            if not isinstance(mtbody, dict):
                continue
            if "example" in mtbody or "examples" in mtbody:
                return True
            if _schema_carries_example(mtbody.get("schema", {}), components):
                return True
    return False


def _public_routes() -> List[APIRoute]:
    """Return every :class:`APIRoute` with ``include_in_schema=True``.

    The list is computed at test collection time and shared across
    the three property tests so the introspection cost is paid once.
    """
    return [
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.include_in_schema
    ]


def _format_offenders(offenders: List[Tuple[str, List[str], str]]) -> str:
    """Format a route-method-reason list for inclusion in a failure message."""
    return "\n".join(
        f"  {method_list[0] if method_list else '?'} {path} — {reason}"
        for path, method_list, reason in offenders
    )


# Feature: api-platform-export, Property 24: Universal documentation annotation
# Validates: Requirements 1.4
def test_p24_every_public_route_has_summary() -> None:
    """Every public route surfaces a non-empty ``summary``.

    Iterates :func:`_public_routes` and collects offending paths
    instead of asserting on the first failure so a single test run
    surfaces the full backlog.
    """
    offenders: List[Tuple[str, List[str], str]] = []
    for route in _public_routes():
        if not (route.summary or "").strip():
            offenders.append(
                (route.path, sorted(route.methods or []), "missing or empty summary")
            )
    if offenders:
        pytest.fail(
            "Public routes missing a non-empty summary:\n"
            + _format_offenders(offenders),
            pytrace=False,
        )


# Feature: api-platform-export, Property 24: Universal documentation annotation
# Validates: Requirements 1.4
def test_p24_every_public_route_has_description() -> None:
    """Every public route surfaces a non-empty ``description``.

    Same enumeration shape as the summary check; description is
    checked as a separate test so a backfill batch can address the
    two axes independently.
    """
    offenders: List[Tuple[str, List[str], str]] = []
    for route in _public_routes():
        if not (route.description or "").strip():
            offenders.append(
                (
                    route.path,
                    sorted(route.methods or []),
                    "missing or empty description",
                )
            )
    if offenders:
        pytest.fail(
            "Public routes missing a non-empty description:\n"
            + _format_offenders(offenders),
            pytrace=False,
        )


# Feature: api-platform-export, Property 24: Universal documentation annotation
# Validates: Requirements 1.4
def test_p24_every_public_operation_has_example() -> None:
    """Every published operation has at least one example response.

    Renders the OpenAPI schema once via :meth:`FastAPI.openapi`,
    walks every operation under ``paths``, and applies the rules in
    :func:`_operation_has_example`. The relaxation for body-less
    successful responses (204) is documented in that helper.
    """
    # Reset any cached schema from earlier tests in the same process
    # so the assertion runs against fresh metadata.
    app.openapi_schema = None
    schema = app.openapi()
    components = schema.get("components", {}).get("schemas", {})
    paths = schema.get("paths", {})

    offenders: List[Tuple[str, List[str], str]] = []
    method_set = {"get", "post", "put", "delete", "patch"}
    for path, methods in paths.items():
        for method, operation in methods.items():
            if method.lower() not in method_set:
                continue
            if not _operation_has_example(operation, components):
                offenders.append(
                    (path, [method.upper()], "no response example surfaces")
                )

    if offenders:
        pytest.fail(
            "Public operations missing a response example:\n"
            + _format_offenders(offenders),
            pytrace=False,
        )
