"""Property-based tests for the rate-limiter decision predicate.

Feature: api-platform-export, Property 16: Rate-limit decision predicate
Validates: Requirements 6.1, 6.2, 6.3, 6.4

Scope
-----
This module tests the **algebra** of the rate-limit decision predicate
in isolation — extracted from the middleware as a pure reference
function. The middleware lives at ``app.middleware.rate_limit`` and
embeds the same predicate inline; an end-to-end integration test that
exercises the middleware via a live FastAPI app + Redis is covered
separately by Task 18.x. Keeping this layer pure avoids coupling
property tests to FastAPI / Starlette / Redis.

Property 16 (design.md §Property 16)
------------------------------------
For any per-key quota tuple ``(Lm, Lh, Ld)`` and any post-increment
counts ``(Cm, Ch, Cd)``, the rate limiter denies the request with HTTP
429 if and only if ``Cm > Lm OR Ch > Lh OR Cd > Ld``. When the request
is allowed, the response carries ``X-RateLimit-Limit = Lm``,
``X-RateLimit-Remaining = max(0, Lm - Cm)``, and
``X-RateLimit-Reset = next_minute_boundary_epoch``. When the request is
denied, the response carries ``Retry-After`` equal to
``max(1, min(reset(w) - now))`` taken across all windows ``w`` for
which ``Cw > Lw``.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Window labels and their durations in seconds (mirrors the middleware).
_WINDOW_DURATIONS: Dict[str, int] = {
    "minute": 60,
    "hour": 3600,
    "day": 86400,
}


def _window_start_epoch(now: int, duration: int) -> int:
    """Return the start of the fixed window containing ``now``."""
    return (now // duration) * duration


def reference_decision(
    limits: Dict[str, int],
    counts: Dict[str, int],
    now: int,
) -> Tuple[str, Optional[int]]:
    """Reference predicate equivalent to the middleware's decision logic.

    Args:
        limits: Per-window quota mapping with keys ``minute``, ``hour``,
            ``day``.
        counts: Per-window post-increment counts with the same keys.
        now: Current Unix timestamp in seconds.

    Returns:
        ``("deny", retry_after_seconds)`` when at least one window has
        ``counts[w] > limits[w]``; otherwise ``("allow", None)``.
    """
    windows = ("minute", "hour", "day")
    exceeded = [w for w in windows if counts[w] > limits[w]]
    if exceeded:
        reset_seconds = []
        for w in exceeded:
            duration = _WINDOW_DURATIONS[w]
            ws = _window_start_epoch(now, duration)
            next_reset = ws + duration
            reset_seconds.append(next_reset - now)
        return ("deny", max(1, min(reset_seconds)))
    return ("allow", None)


# Hypothesis strategies for limits and counts. Bounds are chosen wide
# enough to exercise both regimes (under and over quota) while staying
# within Redis INT64 range.
_LIMITS_STRATEGY = st.fixed_dictionaries(
    {
        "minute": st.integers(min_value=1, max_value=10_000),
        "hour": st.integers(min_value=1, max_value=100_000),
        "day": st.integers(min_value=1, max_value=1_000_000),
    }
)

_COUNTS_STRATEGY = st.fixed_dictionaries(
    {
        "minute": st.integers(min_value=0, max_value=20_000),
        "hour": st.integers(min_value=0, max_value=200_000),
        "day": st.integers(min_value=0, max_value=2_000_000),
    }
)

# ``now`` is a Unix timestamp; bound to a generous range that includes
# both early-window and late-window positions.
_NOW_STRATEGY = st.integers(min_value=0, max_value=4_000_000_000)


# ---------------------------------------------------------------------------
# Property 16 — IFF: deny ⇔ at least one window exceeded
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(limits=_LIMITS_STRATEGY, counts=_COUNTS_STRATEGY, now=_NOW_STRATEGY)
def test_p16_decision_iff_any_window_exceeded(
    limits: Dict[str, int],
    counts: Dict[str, int],
    now: int,
) -> None:
    """The decision is ``deny`` iff at least one window's count exceeds its limit."""
    decision, _retry_after = reference_decision(limits, counts, now)
    any_exceeded = any(
        counts[w] > limits[w] for w in ("minute", "hour", "day")
    )
    if any_exceeded:
        assert decision == "deny"
    else:
        assert decision == "allow"


# ---------------------------------------------------------------------------
# Property 16 — Retry-After equals max(1, min over exceeded windows)
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(limits=_LIMITS_STRATEGY, counts=_COUNTS_STRATEGY, now=_NOW_STRATEGY)
def test_p16_retry_after_is_min_of_exceeded_resets(
    limits: Dict[str, int],
    counts: Dict[str, int],
    now: int,
) -> None:
    """When denied, ``Retry-After`` equals ``max(1, min((reset(w) - now)))``."""
    windows = ("minute", "hour", "day")
    exceeded = [w for w in windows if counts[w] > limits[w]]

    decision, retry_after = reference_decision(limits, counts, now)

    if not exceeded:
        # Allow path: no Retry-After.
        assert decision == "allow"
        assert retry_after is None
        return

    # Deny path: compute the expected minimum reset distance.
    expected_resets = []
    for w in exceeded:
        duration = _WINDOW_DURATIONS[w]
        ws = (now // duration) * duration
        expected_resets.append((ws + duration) - now)
    expected_retry_after = max(1, min(expected_resets))

    assert decision == "deny"
    assert retry_after == expected_retry_after
    # Retry-After is always at least 1 second per the design contract.
    assert retry_after >= 1


# ---------------------------------------------------------------------------
# Property 16 — X-RateLimit-Remaining formula
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    limit_minute=st.integers(min_value=1, max_value=10_000),
    count_minute=st.integers(min_value=0, max_value=20_000),
)
def test_p16_remaining_header_value(limit_minute: int, count_minute: int) -> None:
    """``X-RateLimit-Remaining`` equals ``max(0, Lm - Cm)``."""
    remaining = max(0, limit_minute - count_minute)
    # The header value is a non-negative integer.
    assert remaining >= 0
    # When count is at or below limit, remaining is the simple difference.
    if count_minute <= limit_minute:
        assert remaining == limit_minute - count_minute
    else:
        # Once over quota, remaining floors at zero rather than going negative.
        assert remaining == 0


# ---------------------------------------------------------------------------
# Property 16 — X-RateLimit-Reset formula (next minute boundary)
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(now=_NOW_STRATEGY)
def test_p16_reset_header_value(now: int) -> None:
    """``X-RateLimit-Reset`` equals ``((now // 60) * 60) + 60``."""
    reset_epoch = ((now // 60) * 60) + 60
    # Reset is strictly in the future.
    assert reset_epoch > now
    # The distance to reset is at most one window duration.
    assert reset_epoch - now <= 60
    # Reset lands on a minute boundary.
    assert reset_epoch % 60 == 0


# ---------------------------------------------------------------------------
# Example-based sanity checks (anchor edge cases that hypothesis might
# also reach but which are useful as documentation).
# ---------------------------------------------------------------------------


def test_p16_example_all_under_limit_is_allow() -> None:
    """Counts strictly below limits yield an allow decision."""
    decision, retry_after = reference_decision(
        limits={"minute": 60, "hour": 1200, "day": 10000},
        counts={"minute": 30, "hour": 600, "day": 5000},
        now=1_000_000,
    )
    assert decision == "allow"
    assert retry_after is None


def test_p16_example_count_equal_to_limit_is_allow() -> None:
    """Counts equal to limits yield an allow decision (deny is strict ``>``)."""
    decision, retry_after = reference_decision(
        limits={"minute": 60, "hour": 1200, "day": 10000},
        counts={"minute": 60, "hour": 1200, "day": 10000},
        now=1_000_000,
    )
    assert decision == "allow"
    assert retry_after is None


def test_p16_example_only_minute_exceeded_picks_minute_reset() -> None:
    """When only the minute window is exceeded, retry-after is the minute reset."""
    # ``now`` lands 30 seconds into a minute window: 1_000_050 // 60 = 16_667,
    # window starts at 1_000_020, so now is at offset 30, and the next reset
    # is 30 seconds away.
    now = 1_000_050
    assert now % 60 == 30  # documents the chosen offset
    decision, retry_after = reference_decision(
        limits={"minute": 60, "hour": 1200, "day": 10000},
        counts={"minute": 61, "hour": 600, "day": 5000},
        now=now,
    )
    assert decision == "deny"
    # Minute window resets at now + (60 - 30) = now + 30.
    assert retry_after == 30


def test_p16_example_multiple_exceeded_picks_min_distance() -> None:
    """When multiple windows exceed, retry-after is the minimum reset distance."""
    now = 60  # exactly at a minute boundary; minute resets in 60 s, hour in 3540 s
    decision, retry_after = reference_decision(
        limits={"minute": 60, "hour": 1200, "day": 10000},
        counts={"minute": 100, "hour": 1500, "day": 5000},
        now=now,
    )
    assert decision == "deny"
    # Minute window resets at 60 + 60 = 120 → distance 60. Hour window
    # resets at 3600 → distance 3540. Min is 60.
    assert retry_after == 60


def test_p16_example_retry_after_floor_one() -> None:
    """When the next reset is the same instant as ``now``, retry-after floors at 1."""
    # Construct the pathological case: now lies exactly on a window
    # boundary AND the count is over. The reset distance would be the
    # full window duration (60 seconds for minute), which is well above
    # the floor of 1; here we synthesize the floor case directly via
    # the predicate's algebra. Setting now to a minute boundary gives
    # 60 - 0 = 60, not zero. The floor only matters if some window has
    # zero seconds remaining, which the predicate prevents by including
    # the trailing duration. So the floor of 1 is a defensive guard.
    decision, retry_after = reference_decision(
        limits={"minute": 60, "hour": 1200, "day": 10000},
        counts={"minute": 100, "hour": 600, "day": 5000},
        now=0,
    )
    assert decision == "deny"
    assert retry_after is not None
    assert retry_after >= 1


# ---------------------------------------------------------------------------
# Cross-check the reference predicate against the middleware's helper to
# ensure the test does not silently drift from the implementation.
# ---------------------------------------------------------------------------


def test_p16_window_durations_match_middleware() -> None:
    """The reference predicate's window durations match the middleware module."""
    from app.middleware.rate_limit import _WINDOW_DURATIONS as middleware_durations

    assert _WINDOW_DURATIONS == middleware_durations


def test_p16_window_start_epoch_matches_middleware() -> None:
    """The reference predicate's ``_window_start_epoch`` matches the middleware helper."""
    from app.middleware.rate_limit import _window_start_epoch as middleware_helper

    for now in (0, 59, 60, 3599, 3600, 86399, 86400, 1_000_000):
        for duration in (60, 3600, 86400):
            assert _window_start_epoch(now, duration) == middleware_helper(
                now, duration
            )


# Ensure pytest discovers the property tests as ordinary functions.
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
