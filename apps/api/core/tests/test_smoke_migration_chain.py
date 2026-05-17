"""Task 2.3 — Alembic migration chain integrity smoke test.

The Intelligence Survey Platform's Alembic migrations live under
``apps/api/core/alembic/versions/`` as numbered version modules
(``0001_initial_auth.py`` through ``0011_add_api_platform_indices.py``
at time of writing). Each module exposes module-level ``revision`` and
``down_revision`` literals that together describe a directed graph;
for a healthy single-line history that graph must be a contiguous
parent-to-child chain rooted at ``None`` (the initial revision) and
ending at a unique head with no orphans, no cycles, and no gaps.

These tests walk the version directory by file path, parse each
module's revision metadata via :func:`importlib.util.spec_from_file_location`,
and assert the chain invariants without booting Postgres or running
``alembic upgrade``. Loading by file path is the right primitive here:
Alembic's version modules live outside the regular Python package
graph, are imported by Alembic at runtime via the same primitive, and
should not be reached through ``app.alembic.versions...`` style
imports.

Validates: Requirements 2.1
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Optional, Tuple

# Resolve the versions directory from this test file's location so the
# tests work both when invoked from the repository root and from
# ``apps/api/core/`` directly.
_VERSIONS_DIR = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions"
)


def _load_version_module(path: Path) -> ModuleType:
    """Load a single Alembic version module by file path.

    Alembic version modules are not part of a normal Python package —
    they live in a flat directory and Alembic itself imports them by
    file path. We mirror that here so the test does not need to add
    the alembic versions directory to ``sys.path``.

    Args:
        path: Absolute path to the version module ``.py`` file.

    Returns:
        The loaded module object with its top-level statements
        executed.

    Raises:
        ImportError: When the module cannot be loaded from the path.
    """
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Alembic version module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _collect_revisions() -> List[Tuple[str, Optional[str], str]]:
    """Walk the versions directory and read every module's revision pair.

    Skips ``__init__.py`` and any file whose name does not look like a
    revision module (e.g. unrelated helpers). Returns one tuple per
    module containing the parsed ``revision``, ``down_revision``, and
    the module file name for use in failure messages.

    Returns:
        A list of ``(revision, down_revision, file_name)`` tuples in
        directory-listing order.
    """
    rows: List[Tuple[str, Optional[str], str]] = []
    for path in sorted(_VERSIONS_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        module = _load_version_module(path)
        revision = getattr(module, "revision", None)
        down_revision = getattr(module, "down_revision", None)
        # Skip helper modules that do not declare an Alembic revision.
        if revision is None:
            continue
        rows.append((revision, down_revision, path.name))
    return rows


# Feature: api-platform-export, Property: Migration chain integrity
# Validates: Requirements 2.1
def test_chain_is_contiguous_from_initial_to_head() -> None:
    """The chain forms a single contiguous sequence from ``None`` to the head.

    Builds a parent-to-children mapping and walks forward from the
    root (the lone revision whose ``down_revision`` is ``None``).
    Every revision must appear exactly once on the walk, and the walk
    must terminate at a unique head with no children.
    """
    rows = _collect_revisions()
    assert rows, (
        f"No Alembic version modules discovered under {_VERSIONS_DIR}; "
        "the migration chain cannot be validated"
    )

    revisions: Dict[str, Optional[str]] = {}
    for revision, down_revision, file_name in rows:
        assert revision not in revisions, (
            f"Duplicate revision id {revision!r} in {file_name}"
        )
        revisions[revision] = down_revision

    # Roots: revisions whose down_revision is None.
    roots = [rev for rev, down in revisions.items() if down is None]
    assert len(roots) == 1, (
        f"Expected exactly one root revision (down_revision is None); "
        f"found {sorted(roots)}"
    )
    root = roots[0]

    # Build forward adjacency: parent -> [children].
    children: Dict[str, List[str]] = {rev: [] for rev in revisions}
    for rev, down in revisions.items():
        if down is None:
            continue
        assert down in revisions, (
            f"Revision {rev!r} declares down_revision {down!r} which "
            f"does not exist; chain has a dangling parent reference"
        )
        children[down].append(rev)

    # Walk forward from the root. A contiguous chain means each node
    # has at most one child, every node is reachable, and exactly one
    # node has zero children (the head).
    visited: List[str] = []
    cursor: Optional[str] = root
    while cursor is not None:
        visited.append(cursor)
        nexts = children[cursor]
        assert len(nexts) <= 1, (
            f"Revision {cursor!r} has multiple children {nexts}; "
            "chain is branched and not a single contiguous sequence"
        )
        cursor = nexts[0] if nexts else None

    assert set(visited) == set(revisions), (
        f"Walk reached {len(visited)} of {len(revisions)} revisions; "
        f"orphaned revisions: {sorted(set(revisions) - set(visited))}"
    )


# Feature: api-platform-export, Property: Migration chain integrity
# Validates: Requirements 2.1
def test_chain_has_no_cycles() -> None:
    """Depth-first traversal from the root detects no back-edge.

    Traces the chain by following ``down_revision`` from each node up
    toward the root. A cycle would manifest as a node revisiting one
    of its ancestors before reaching ``None``.
    """
    rows = _collect_revisions()
    revisions: Dict[str, Optional[str]] = {
        rev: down for rev, down, _ in rows
    }

    for start in revisions:
        seen: List[str] = []
        cursor: Optional[str] = start
        while cursor is not None:
            assert cursor not in seen, (
                f"Cycle detected starting at {start!r}: revisited "
                f"{cursor!r} after path {seen}"
            )
            seen.append(cursor)
            assert cursor in revisions, (
                f"Path from {start!r} reached unknown revision "
                f"{cursor!r}; chain is broken"
            )
            cursor = revisions[cursor]


# Feature: api-platform-export, Property: Migration chain integrity
# Validates: Requirements 2.1
def test_chain_head_is_0011_or_later() -> None:
    """The head revision is ``0011`` or later.

    The current design extends the chain through revision ``0011``
    (composite indices for the API platform). A head earlier than
    that means the migration set has regressed; a head later than
    that is permitted, since new migrations land on top of the
    existing chain.
    """
    rows = _collect_revisions()
    revisions = {rev: down for rev, down, _ in rows}

    children = {rev: 0 for rev in revisions}
    for rev, down in revisions.items():
        if down is not None:
            children[down] = children.get(down, 0) + 1
    heads = [rev for rev, count in children.items() if count == 0]
    assert len(heads) == 1, (
        f"Expected exactly one head revision; found {sorted(heads)}"
    )
    head = heads[0]
    assert head >= "0011", (
        f"Head revision {head!r} is earlier than 0011; the API "
        "platform migration set is not present in the chain"
    )
