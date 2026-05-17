"""Task 1.4 — Audit row schema mapping unit tests.

The :class:`app.models.audit_log.AuditLog` ORM row exposes a fixed
column surface that the design document pins down in
``.kiro/specs/api-platform-export/design.md`` §Component 10. Per
Requirement 7.9, audit details fields that do not map onto a
schema-compatible column must be silently absorbed into the JSONB
``details`` column rather than triggering a schema migration. The
public helper :func:`app.core.audit.log_audit` is the single
write-path that every T15 verb exercises, and its argument shape is
itself the schema-compatible projection.

These tests are pure metadata reflection: they do not boot a database
session, do not import the FastAPI app, and do not exercise any
network or Redis code path. They lock in three properties.

1. The ORM table carries every column the design names canonical.
2. The ``details`` column type is a Postgres JSONB instance, so it can
   absorb arbitrary JSON-serializable extras per Req 7.9.
3. The :func:`log_audit` helper signature continues to accept the six
   keyword arguments documented in design §Component 10 and exercised
   by every existing call site.

Validates: Requirements 7.8, 7.9
"""

from __future__ import annotations

import inspect

from sqlalchemy.dialects.postgresql import JSONB

from app.core.audit import log_audit
from app.models.audit_log import AuditLog


# Canonical eight-column projection from design §Component 10. Listed
# here as a frozenset so test failures highlight set differences
# directly rather than ordering accidents.
_DESIGN_CANONICAL_COLUMNS = frozenset(
    {
        "user_id",
        "action",
        "resource_type",
        "resource_id",
        "details",
        "ip_address",
        "user_agent",
        "created_at",
    }
)


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8
def test_audit_log_columns_match_design_section_data_models() -> None:
    """The ORM table is a superset of the canonical eight-column projection.

    Reflects ``AuditLog.__table__.columns.keys()`` and asserts the
    eight columns named by the design are present. The model also
    carries a primary-key ``id``; the assertion is a superset rather
    than equality to leave room for future bookkeeping columns
    without forcing a test rewrite.
    """
    declared = set(AuditLog.__table__.columns.keys())
    missing = _DESIGN_CANONICAL_COLUMNS - declared
    assert not missing, (
        f"AuditLog table is missing canonical columns: {sorted(missing)}; "
        f"declared columns are {sorted(declared)}"
    )


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.9
def test_audit_log_details_is_jsonb() -> None:
    """The ``details`` column accepts arbitrary JSON-serializable dicts.

    Inspects the SQLAlchemy column type rather than running a write
    path — JSONB is the storage primitive that lets unknown extras
    flow through unchanged. Without JSONB the silently-drop semantics
    required by Req 7.9 would not be implementable at the column
    layer.
    """
    column = AuditLog.__table__.columns["details"]
    assert isinstance(column.type, JSONB), (
        f"AuditLog.details type is {type(column.type).__name__}; "
        "expected JSONB so the column can absorb arbitrary "
        "JSON-serializable extras per Req 7.9"
    )


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
def test_log_audit_signature_documented() -> None:
    """The :func:`log_audit` helper exposes the six documented kwargs.

    The helper is the only write surface T15 components use; pinning
    its signature keeps the audit contract stable across refactors.
    The check is a name-level inspection, not a type-level one, so
    Pydantic / annotation evolution is allowed but the canonical
    parameter names are not.
    """
    sig = inspect.signature(log_audit)
    documented = {"action", "user_id", "resource_type", "resource_id", "details", "request"}
    parameters = set(sig.parameters)
    missing = documented - parameters
    assert not missing, (
        f"log_audit is missing documented kwargs: {sorted(missing)}; "
        f"actual signature parameters are {sorted(parameters)}"
    )
