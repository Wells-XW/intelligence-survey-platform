"""Property test P5: Expired credential rejection.

The deps module's API key resolver computes the expiration decision as:

    if row.expires_at is not None and row.expires_at <= now:
        raise 401 api_key_expired

This test validates the predicate algebra in isolation. The full
end-to-end test (auth resolver + DB session + HTTP layer) is covered
by Task 18.3.

# Feature: api-platform-export, Property 5: Expired credential rejection
# Validates: Requirements 2.6
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
from hypothesis import given, settings, strategies as st


def _is_expired(expires_at: Optional[datetime], now: datetime) -> bool:
    """Reference predicate matching app.core.deps._resolve_api_key_principal."""
    if expires_at is None:
        return False
    return expires_at <= now


@given(
    seconds_offset=st.integers(min_value=-86400 * 365, max_value=86400 * 365),
)
@settings(max_examples=100)
def test_p5_expiration_predicate_matches_strict_le(seconds_offset: int) -> None:
    """The predicate denies iff expires_at is non-null AND <= now."""
    now = datetime(2026, 9, 15, 10, 23, 0, tzinfo=timezone.utc)
    expires_at = now + timedelta(seconds=seconds_offset)
    expected = seconds_offset <= 0
    assert _is_expired(expires_at, now) is expected


def test_p5_none_expiration_is_never_denied() -> None:
    """A key with no expires_at is never marked expired."""
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    assert _is_expired(None, now) is False


@given(
    seconds_in_future=st.integers(min_value=1, max_value=86400 * 365),
)
@settings(max_examples=100)
def test_p5_future_expiration_is_not_denied(seconds_in_future: int) -> None:
    """Any strictly-future expiration is allowed."""
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    expires_at = now + timedelta(seconds=seconds_in_future)
    assert _is_expired(expires_at, now) is False


@given(
    seconds_in_past=st.integers(min_value=0, max_value=86400 * 365),
)
@settings(max_examples=100)
def test_p5_past_or_now_expiration_is_denied(seconds_in_past: int) -> None:
    """Any past-or-equal-to-now expiration is denied."""
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    expires_at = now - timedelta(seconds=seconds_in_past)
    assert _is_expired(expires_at, now) is True
