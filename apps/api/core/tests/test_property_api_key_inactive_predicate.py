"""Property test P6: Inactive flag predicate.

The list endpoint at ``GET /api/v1/api-keys/`` returns each row with a
boolean ``inactive`` flag computed by the helper
:func:`app.api.v1.api_keys._is_inactive`. Per design §Property 6, that
flag must equal::

    inactive == (now - coalesce(last_used_at, created_at)) >= threshold

This module tests the predicate directly without booting the FastAPI
app or the database, since the helper is a pure function over a duck
type with ``last_used_at`` and ``created_at`` attributes. We use
:class:`types.SimpleNamespace` to stand in for the
:class:`app.models.api_key.ApiKey` ORM row and feed the predicate
hypothesised offsets that span the past, the present, and the future.

# Feature: api-platform-export, Property 6: Inactive flag predicate
# Validates: Requirements 2.9
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

from hypothesis import given, settings, strategies as st

from app.api.v1.api_keys import _is_inactive


# Anchor "now" used by every example. Holding it constant keeps the
# property algebra reproducible and avoids dependencies on the
# system clock during shrinking.
_NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


def _reference_predicate(
    last_used_at: Optional[datetime],
    created_at: datetime,
    now: datetime,
    threshold: timedelta,
) -> bool:
    """Reference implementation of the design §Property 6 predicate.

    Mirrors the natural-language statement verbatim so any divergence
    between the helper under test and this function surfaces as a
    Hypothesis counterexample rather than a buried bug.
    """
    last_seen = last_used_at if last_used_at is not None else created_at
    return (now - last_seen) >= threshold


# Strategy generates seconds-from-now offsets in a wide window
# centred on _NOW. The asymmetry (more past than future) is
# deliberate: the predicate's interesting region is the past side of
# now where ``inactive`` can flip to True.
_OFFSET_SECONDS = st.integers(
    min_value=-365 * 86400,
    max_value=30 * 86400,
)

# Threshold spans 1 day to 365 days; matches the inactivity threshold
# settings the Settings class exposes (default 90 days) plus a wide
# margin on either side.
_THRESHOLD_DAYS = st.integers(min_value=1, max_value=365)


# Feature: api-platform-export, Property 6: Inactive flag predicate
# Validates: Requirements 2.9
@given(
    last_used_offset_seconds=st.one_of(
        st.none(),
        _OFFSET_SECONDS,
    ),
    created_offset_seconds=_OFFSET_SECONDS,
    threshold_days=_THRESHOLD_DAYS,
)
@settings(max_examples=100, deadline=None)
def test_p6_inactive_matches_reference_predicate(
    last_used_offset_seconds: Optional[int],
    created_offset_seconds: int,
    threshold_days: int,
) -> None:
    """The helper agrees with the design's reference predicate.

    Builds a stand-in row with the hypothesised timestamps, invokes
    :func:`_is_inactive`, and compares the result against the
    reference predicate from design §Property 6.
    """
    last_used_at = (
        _NOW + timedelta(seconds=last_used_offset_seconds)
        if last_used_offset_seconds is not None
        else None
    )
    created_at = _NOW + timedelta(seconds=created_offset_seconds)
    threshold = timedelta(days=threshold_days)

    row = SimpleNamespace(last_used_at=last_used_at, created_at=created_at)

    actual = _is_inactive(row, _NOW, threshold)
    expected = _reference_predicate(last_used_at, created_at, _NOW, threshold)

    assert actual is expected, (
        f"_is_inactive disagreed with reference predicate: "
        f"last_used_at={last_used_at}, created_at={created_at}, "
        f"threshold={threshold}, now={_NOW}; "
        f"got {actual}, expected {expected}"
    )


# Feature: api-platform-export, Property 6: Inactive flag predicate
# Validates: Requirements 2.9
def test_p6_none_last_used_uses_created_at() -> None:
    """When ``last_used_at`` is None the predicate falls back to ``created_at``.

    Two paired cases pin the fallback:

    * ``created_at`` 100 days in the past with a 90-day threshold —
      inactive.
    * ``created_at`` 30 days in the past with a 90-day threshold —
      active.
    """
    threshold = timedelta(days=90)

    inactive_row = SimpleNamespace(
        last_used_at=None,
        created_at=_NOW - timedelta(days=100),
    )
    assert _is_inactive(inactive_row, _NOW, threshold) is True

    active_row = SimpleNamespace(
        last_used_at=None,
        created_at=_NOW - timedelta(days=30),
    )
    assert _is_inactive(active_row, _NOW, threshold) is False


# Feature: api-platform-export, Property 6: Inactive flag predicate
# Validates: Requirements 2.9
def test_p6_recent_last_used_overrides_old_created_at() -> None:
    """A recent ``last_used_at`` wins over an old ``created_at``.

    A key created a year ago but used today must read as active —
    confirms the predicate uses ``last_used_at`` when present rather
    than always defaulting to creation time.
    """
    row = SimpleNamespace(
        last_used_at=_NOW - timedelta(hours=1),
        created_at=_NOW - timedelta(days=365),
    )
    assert _is_inactive(row, _NOW, timedelta(days=90)) is False
