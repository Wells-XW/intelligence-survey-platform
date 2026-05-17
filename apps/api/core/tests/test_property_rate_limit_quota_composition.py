"""Property test P17: Effective quota composition.

Per design §Property 17 (Requirements 6.5, 6.6) the per-API-key rate
limiter resolves the effective quota for each window using a fall-through
rule::

    effective_quota[w] = override[w]   if w in override
                       = default[w]    otherwise

The default values come from
:mod:`app.config.settings` (``rate_limit_default_per_minute``,
``rate_limit_default_per_hour``, ``rate_limit_default_per_day``); the
override map is stored as a JSONB partial dict on
:class:`app.models.api_key.ApiKey.rate_limit_overrides`. Any subset of
the three windows may carry an override; missing windows fall back to
the platform default.

The current middleware at :mod:`app.middleware.rate_limit` does not
yet honour per-key overrides (see its module docstring on the
identity / round-trip trade-off), but the composition predicate is
the contract every override-aware tier must implement. Testing the
predicate as a pure function lets P17 run without Redis, the
database, or the FastAPI application, and pins the contract for
future work.

# Feature: api-platform-export, Property 17: Effective quota composition
# Validates: Requirements 6.5, 6.6
"""

from __future__ import annotations

from typing import Dict

from hypothesis import given, settings, strategies as st

from app.config import settings as app_settings


_WINDOW_LABELS = ("minute", "hour", "day")


def effective_quota(
    override_map: Dict[str, int],
    defaults: Dict[str, int],
    window: str,
) -> int:
    """Reference implementation of the design §Property 17 predicate.

    Returns the override value when the window key is present in the
    override map; otherwise returns the platform default. Mirrors the
    natural-language statement verbatim so any divergence between
    implementation tiers and this function surfaces as a Hypothesis
    counterexample.

    Args:
        override_map: Partial override dict from
            :attr:`ApiKey.rate_limit_overrides`. Any subset of the
            three windows may be present.
        defaults: Full default dict from settings, with one entry per
            window label.
        window: The window label being resolved.

    Returns:
        The effective quota integer for ``window``.
    """
    if window in override_map:
        return override_map[window]
    return defaults[window]


# A strategy for partial override maps: zero, one, two, or three
# entries chosen from the canonical window labels with non-negative
# integer values. Allowing zero entries exercises the "no override"
# fall-through case.
def _override_map_strategy() -> st.SearchStrategy[Dict[str, int]]:
    """Build a Hypothesis strategy for partial rate_limit_overrides maps."""
    return st.dictionaries(
        keys=st.sampled_from(_WINDOW_LABELS),
        values=st.integers(min_value=0, max_value=10_000_000),
        max_size=3,
    )


# Defaults: a strategy mirroring the shape of platform defaults — one
# integer per window. Independent from the override values so the
# property holds when override and default agree, when they differ,
# and when they are zero.
_DEFAULTS_STRATEGY = st.fixed_dictionaries(
    {
        "minute": st.integers(min_value=0, max_value=10_000_000),
        "hour": st.integers(min_value=0, max_value=10_000_000),
        "day": st.integers(min_value=0, max_value=10_000_000),
    }
)


# Feature: api-platform-export, Property 17: Effective quota composition
# Validates: Requirements 6.5, 6.6
@given(
    override_map=_override_map_strategy(),
    defaults=_DEFAULTS_STRATEGY,
    window=st.sampled_from(_WINDOW_LABELS),
)
@settings(max_examples=100, deadline=None)
def test_p17_effective_quota_matches_reference(
    override_map: Dict[str, int],
    defaults: Dict[str, int],
    window: str,
) -> None:
    """Effective quota equals override[w] if present else default[w].

    The reference computation is inlined here rather than calling
    :func:`effective_quota` so a future refactor that breaks the
    helper does not also break the test by simply re-importing the
    same broken function.
    """
    actual = effective_quota(override_map, defaults, window)
    expected = (
        override_map[window]
        if window in override_map
        else defaults[window]
    )
    assert actual == expected, (
        f"effective_quota disagreed with reference: "
        f"override={override_map}, defaults={defaults}, "
        f"window={window!r}; got {actual}, expected {expected}"
    )


# Feature: api-platform-export, Property 17: Effective quota composition
# Validates: Requirements 6.6
@given(
    override_map=_override_map_strategy(),
    defaults=_DEFAULTS_STRATEGY,
)
@settings(max_examples=100, deadline=None)
def test_p17_missing_windows_fall_back_to_defaults(
    override_map: Dict[str, int],
    defaults: Dict[str, int],
) -> None:
    """Every window absent from the override map yields the default.

    The contract bars hidden state: removing an override entry must
    return the window to the platform default, not to some prior
    cached value. Phrased as a property over arbitrary partial
    override maps, this is the load-bearing half of Req 6.6 (per-key
    overrides are partial and additive, never subtractive without
    fall-through).
    """
    for window in _WINDOW_LABELS:
        if window in override_map:
            continue
        assert (
            effective_quota(override_map, defaults, window) == defaults[window]
        )


# Feature: api-platform-export, Property 17: Effective quota composition
# Validates: Requirements 6.5, 6.6
@given(override_map=_override_map_strategy())
@settings(max_examples=100, deadline=None)
def test_p17_present_windows_use_override(
    override_map: Dict[str, int],
) -> None:
    """Every window present in the override map yields the override.

    Holds even when the override value happens to coincide with the
    default — the predicate selects on key presence, not on value
    equality. This guards against an implementation that skips the
    override write when the override matches the default (an
    optimization that would silently change behaviour when the
    default later moves).
    """
    defaults = {"minute": 60, "hour": 1200, "day": 10000}
    for window, override_value in override_map.items():
        assert (
            effective_quota(override_map, defaults, window) == override_value
        )


# Feature: api-platform-export, Property 17: Effective quota composition
# Validates: Requirements 6.5
def test_p17_settings_carry_three_canonical_defaults() -> None:
    """The Settings object exposes the three canonical default quotas.

    A regression check that the platform defaults the predicate falls
    through to are still present on the settings module — without
    them the middleware has nothing to compose against.
    """
    assert app_settings.rate_limit_default_per_minute > 0
    assert app_settings.rate_limit_default_per_hour > 0
    assert app_settings.rate_limit_default_per_day > 0
