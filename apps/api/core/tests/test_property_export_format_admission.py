"""Property tests for export format admission (Property 12).

These tests validate that the runtime ``SUPPORTED_FORMATS`` set in
``app.services.export_formats`` is exactly the set of strings that the
create-export endpoint will accept, and that any non-member is
rejected. The endpoint itself is not exercised here — design.md
§Property 12 explicitly notes the property is testable as a pure
predicate on the module-level set, which keeps the test independent
of FastAPI / database fixtures and lets Hypothesis explore a large
input space cheaply.

Reference: design.md §Property 12. Validates Requirements 5.1, 5.2,
5.3.
"""

from __future__ import annotations

import string

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.export_formats import (  # type: ignore[attr-defined]
    SUPPORTED_FORMATS,
    _PYREADSTAT_AVAILABLE,
)

# Required baseline formats per Req 5.1.
_BASELINE_FORMATS = frozenset({"csv", "xlsx", "json"})

# Conditional formats per Req 5.2 — only present when pyreadstat imports.
# The SAS path is XPORT (.xpt) rather than .sas7bdat because pyreadstat
# ships only a SAS7BDAT reader; XPORT is the supported write format.
_PYREADSTAT_FORMATS = frozenset({"sav", "xpt"})


def _expected_membership(f: str) -> bool:
    """Reference predicate for Property 12.

    A format string ``f`` should be admitted by the create endpoint if
    and only if:
      * ``f`` is one of the baseline formats {csv, xlsx, json}, OR
      * ``pyreadstat`` is importable in this worker's environment and
        ``f`` is one of {sav, xpt}.

    Any other input — empty strings, garbage, partial prefixes,
    capitalisation variants — must be rejected with HTTP 400 +
    ``export_format_unsupported`` (Req 5.3).
    """
    if f in _BASELINE_FORMATS:
        return True
    if _PYREADSTAT_AVAILABLE and f in _PYREADSTAT_FORMATS:
        return True
    return False


# Feature: api-platform-export, Property 12: Export format admission
def test_p12_supported_formats_includes_required_baseline() -> None:
    """Req 5.1 demands csv/xlsx/json are always supported.

    This is a non-negotiable invariant of the producer registry: even
    when ``pyreadstat`` is missing, the three baseline formats must
    still be admitted by the export pipeline.
    """
    assert _BASELINE_FORMATS <= SUPPORTED_FORMATS


# Feature: api-platform-export, Property 12: Export format admission
@given(
    f=st.text(
        alphabet=string.ascii_lowercase + string.digits,
        min_size=1,
        max_size=20,
    ),
)
@settings(max_examples=100)
def test_p12_arbitrary_format_string_admission_predicate(f: str) -> None:
    """Membership in ``SUPPORTED_FORMATS`` matches the reference predicate.

    The Hypothesis search space is restricted to lowercase ASCII +
    digits because format strings on the create endpoint are
    case-sensitive lowercase identifiers. We do not test casing
    variants here (those are covered by route-level validation tests),
    only that the set membership predicate is exactly equivalent to
    the runtime acceptance decision.

    Validates: Requirements 5.1, 5.2, 5.3.
    """
    assert (f in SUPPORTED_FORMATS) is _expected_membership(f)


# Feature: api-platform-export, Property 12: Export format admission
def test_p12_pyreadstat_extends_supported_formats_consistently() -> None:
    """Conditional sav/xpt support tracks the pyreadstat probe.

    The module-private ``_PYREADSTAT_AVAILABLE`` flag is the single
    source of truth for whether the SPSS / SAS producers loaded; this
    test pins the public set's behaviour to that flag so a future
    refactor cannot silently desynchronise them.

    Validates: Requirement 5.2.
    """
    if _PYREADSTAT_AVAILABLE:
        assert "sav" in SUPPORTED_FORMATS
        assert "xpt" in SUPPORTED_FORMATS
    else:
        assert "sav" not in SUPPORTED_FORMATS
        assert "xpt" not in SUPPORTED_FORMATS
