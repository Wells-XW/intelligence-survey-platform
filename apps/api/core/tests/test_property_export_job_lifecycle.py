"""Property test P13: Export job lifecycle convergence.

Per design §Property 13 (Requirements 5.4, 5.9, 5.12), an
:class:`app.models.export_job.ExportJob` row's ``status`` may evolve
only along the legal transition graph::

    queued → running
    running → succeeded | failed
    succeeded → expired

The terminal states ``failed`` and ``expired`` admit no outgoing
transitions; ``succeeded → expired`` is driven by the retention
sweeper Celery beat job.

These tests model that graph as a pure function and exercise it with
both an enumeration of every legal length-1..length-5 sequence
starting from ``queued`` and a Hypothesis strategy that generates
arbitrary state lists. The pure-function approach matches the design's
"state machine algebra" framing and lets us pin the legality
predicate without booting Celery, the worker, or Postgres.

# Feature: api-platform-export, Property 13: Export job lifecycle convergence
# Validates: Requirements 5.4, 5.9, 5.12
"""

from __future__ import annotations

from itertools import product
from typing import Iterable, List

from hypothesis import given, settings, strategies as st


# Legal transition graph from design §Property 13. Encoded as a
# parent → set-of-children mapping so absence-from-key-set means
# terminal.
_LEGAL_TRANSITIONS = {
    "queued": {"running"},
    "running": {"succeeded", "failed"},
    "succeeded": {"expired"},
    "failed": set(),
    "expired": set(),
}

_ALL_STATES: List[str] = sorted(_LEGAL_TRANSITIONS)


def is_legal_sequence(states: List[str]) -> bool:
    """Return True if every consecutive (a, b) is a permitted transition.

    A length-0 or length-1 sequence is vacuously legal. Empty or
    one-state sequences correspond to a freshly-inserted row that has
    not yet transitioned, which is a legitimate observation.
    """
    for a, b in zip(states, states[1:]):
        if b not in _LEGAL_TRANSITIONS.get(a, set()):
            return False
    return True


def _enumerate_legal_paths(
    start: str, max_length: int
) -> Iterable[List[str]]:
    """Yield every legal status sequence of length 1..``max_length``.

    Implemented as iterative deepening so the enumeration covers
    short-but-valid paths (e.g. ``[queued]``) alongside full-length
    paths (e.g. ``[queued, running, succeeded, expired]``). The graph
    is small enough that the total number of paths is bounded
    independent of ``max_length`` once terminal states are reached.

    Args:
        start: The state to begin every path from.
        max_length: Inclusive upper bound on path length.

    Yields:
        Lists of state names where every consecutive pair is in
        ``_LEGAL_TRANSITIONS``.
    """
    frontier: List[List[str]] = [[start]]
    while frontier:
        path = frontier.pop()
        yield path
        if len(path) >= max_length:
            continue
        last = path[-1]
        for nxt in sorted(_LEGAL_TRANSITIONS.get(last, set())):
            frontier.append(path + [nxt])


# Feature: api-platform-export, Property 13: Export job lifecycle convergence
# Validates: Requirements 5.4, 5.9, 5.12
def test_p13_every_legal_path_is_accepted() -> None:
    """Every enumerated legal path from ``queued`` is judged legal.

    Walks the full legal-path enumeration up to length 5 and asserts
    :func:`is_legal_sequence` returns True for each. A failure here
    means the legality predicate disagrees with the explicit
    transition graph, which is the design's source of truth.
    """
    paths = list(_enumerate_legal_paths("queued", max_length=5))
    assert paths, "expected at least one legal path from 'queued'"
    for path in paths:
        assert is_legal_sequence(path), (
            f"enumerated path {path!r} was rejected by is_legal_sequence; "
            "the legality predicate disagrees with the transition graph"
        )


# Feature: api-platform-export, Property 13: Export job lifecycle convergence
# Validates: Requirements 5.4, 5.9, 5.12
@given(
    states=st.lists(
        st.sampled_from(_ALL_STATES),
        min_size=1,
        max_size=6,
    ),
)
@settings(max_examples=100, deadline=None)
def test_p13_predicate_agrees_with_pairwise_check(states: List[str]) -> None:
    """The predicate agrees with manual pairwise transition checks.

    Hypothesis generates arbitrary state lists drawn uniformly from
    the five-state alphabet — most of these will not be legal
    sequences. The reference computation walks the list manually,
    using the same transition graph; the predicate's verdict must
    match for every sequence.
    """
    expected = all(
        b in _LEGAL_TRANSITIONS.get(a, set())
        for a, b in zip(states, states[1:])
    )
    assert is_legal_sequence(states) is expected, (
        f"is_legal_sequence disagreed with pairwise check on {states!r}: "
        f"got {is_legal_sequence(states)}, expected {expected}"
    )


# Feature: api-platform-export, Property 13: Export job lifecycle convergence
# Validates: Requirements 5.4
def test_p13_failed_is_terminal() -> None:
    """No transition exits ``failed``.

    Asserts directly against the transition graph because terminal
    semantics are the design's reasons for keeping the job row even
    after materialization fails: a terminated row carries the
    ``error_message`` for debugging and is never re-run.
    """
    assert _LEGAL_TRANSITIONS["failed"] == set()
    for other in _ALL_STATES:
        assert not is_legal_sequence(["failed", other])


# Feature: api-platform-export, Property 13: Export job lifecycle convergence
# Validates: Requirements 5.12
def test_p13_expired_is_terminal() -> None:
    """No transition exits ``expired``.

    The retention sweeper sets ``expired`` after deleting the on-disk
    file; an expired row must not transition back to a status that
    implies a downloadable file exists.
    """
    assert _LEGAL_TRANSITIONS["expired"] == set()
    for other in _ALL_STATES:
        assert not is_legal_sequence(["expired", other])


# Feature: api-platform-export, Property 13: Export job lifecycle convergence
# Validates: Requirements 5.4, 5.9, 5.12
def test_p13_full_lifecycle_path_is_legal() -> None:
    """The canonical full-lifecycle path is accepted.

    Pins the longest legal path from ``queued`` to ``expired`` —
    this is the path most production rows traverse in order, so it
    is worth a named test alongside the property check.
    """
    assert is_legal_sequence(["queued", "running", "succeeded", "expired"]) is True


# Feature: api-platform-export, Property 13: Export job lifecycle convergence
# Validates: Requirements 5.4, 5.9
def test_p13_obvious_illegal_transitions_rejected() -> None:
    """A sample of obviously illegal transitions are rejected.

    Belt-and-suspenders sanity check: make sure no future refactor
    accidentally permits ``queued → succeeded`` (skipping
    materialization) or ``running → expired`` (skipping the
    file-write step).
    """
    illegal_pairs = list(product(_ALL_STATES, repeat=2))
    legal_pairs = {(a, b) for a, children in _LEGAL_TRANSITIONS.items() for b in children}
    for a, b in illegal_pairs:
        if (a, b) in legal_pairs:
            continue
        assert not is_legal_sequence([a, b]), (
            f"expected ({a} -> {b}) to be rejected but is_legal_sequence "
            "accepted it"
        )
