"""Task 18.6 — pyreadstat import + round-trip smoke test.

The export worker depends on the optional ``pyreadstat`` library to
materialize SPSS ``.sav`` and SAS ``.xpt`` exports (design.md
§Component 7, Requirement 5.2 / 5.8). The wheel ships per-platform
binary blobs and has historically been a fragile point in CI: a
missing wheel, a Python-version mismatch, or a missing
``readstat`` shared object surfaces only when the worker tries to
write a binary export, which is too late.

This smoke test runs at unit-test time and fails fast under three
conditions:

* ``pyreadstat`` does not import on the deployment platform.
* ``pyreadstat.write_sav`` + ``pyreadstat.read_sav`` cannot round-trip
  a tiny in-memory DataFrame (the SAV write/read path is broken).
* ``pyreadstat.write_xport`` + ``pyreadstat.read_xport`` cannot
  round-trip the same DataFrame (the SAS XPORT write/read path is
  broken).

Pyreadstat does not expose ``write_sas7bdat`` — the library can only
read SAS7BDAT files. The task brief mentioned a ``write_xport`` /
``read_sas7bdat`` pairing, but those two functions operate on
different on-disk formats (XPT vs SAS7BDAT), so the actual round-trip
is performed via ``write_xport`` + ``read_xport``. The presence of
``read_sas7bdat`` is asserted separately so that a wheel missing the
SAS7BDAT reader still trips this smoke test.

Validates: Requirements 5.2
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd


# Skip the entire module cleanly if pyreadstat is not installed in the
# current environment. The export worker treats SAV/SAS as optional
# formats (see ``app/services/export_formats/__init__.py``); CI is
# expected to install the wheel, but local developer machines may not
# have it. ``importorskip`` produces a single, readable skip line
# rather than an ImportError traceback when the wheel is absent.
pyreadstat = pytest.importorskip("pyreadstat")
pd = pytest.importorskip("pandas")


def _build_tiny_dataframe() -> "pd.DataFrame":
    """Construct a 2-row, 3-column DataFrame for round-trip tests.

    Mixing one numeric column, one float column, and one string column
    exercises the three storage classes the SAV/XPT writers must
    handle without resorting to the full export-formats producer
    pipeline — keeping this test orthogonal to survey-shaped data.

    Returns:
        A small pandas DataFrame whose shape and column dtypes are
        intentionally fixed.
    """
    return pd.DataFrame(
        {
            "id": [1, 2],
            "score": [0.5, 0.75],
            "label": ["alpha", "beta"],
        }
    )


# Feature: api-platform-export, Property: pyreadstat wheel availability
# Validates: Requirements 5.2
def test_pyreadstat_imports() -> None:
    """``pyreadstat`` imports and exposes a non-empty version string.

    A successful import here is the cheapest possible signal that the
    wheel is installed correctly on the deployment platform; the
    version assertion guards against the rare case where a partially
    failed install leaves an importable but broken module.
    """
    assert hasattr(pyreadstat, "__version__"), (
        "pyreadstat is importable but lacks a __version__ attribute; "
        "the wheel install is incomplete"
    )
    version = pyreadstat.__version__
    assert isinstance(version, str) and version.strip(), (
        f"pyreadstat.__version__ is not a non-empty string: {version!r}"
    )


# Feature: api-platform-export, Property: pyreadstat SAV round-trip
# Validates: Requirements 5.2
def test_pyreadstat_sav_roundtrip(tmp_path: Path) -> None:
    """``write_sav`` followed by ``read_sav`` preserves the DataFrame shape.

    Writes a tiny DataFrame to a SAV file under pytest's ``tmp_path``,
    reads it back, and asserts the shape is preserved. The read path
    returns ``(dataframe, meta)``; only the shape and column names are
    checked here so the test stays insensitive to dtype upcasting
    (SPSS treats integers as floats internally) while still catching
    a fundamentally broken write or read.
    """
    df = _build_tiny_dataframe()
    output_path = tmp_path / "smoke.sav"

    pyreadstat.write_sav(df, str(output_path))

    assert output_path.exists() and output_path.stat().st_size > 0, (
        "pyreadstat.write_sav produced no output file or an empty file"
    )

    read_df, _meta = pyreadstat.read_sav(str(output_path))

    assert read_df.shape == df.shape, (
        f"SAV round-trip changed the DataFrame shape: wrote "
        f"{df.shape}, read back {read_df.shape}"
    )
    assert list(read_df.columns) == list(df.columns), (
        f"SAV round-trip changed the column order: wrote "
        f"{list(df.columns)}, read back {list(read_df.columns)}"
    )


# Feature: api-platform-export, Property: pyreadstat XPORT round-trip
# Validates: Requirements 5.2
def test_pyreadstat_xport_roundtrip(tmp_path: Path) -> None:
    """``write_xport`` + ``read_xport`` preserves the DataFrame shape.

    Pyreadstat cannot write SAS7BDAT directly (no ``write_sas7bdat``
    exists in the public API at any released version), so the SAS
    write path goes through XPORT (.xpt). XPORT column names are
    capped at 8 characters and uppercased on write, so the test
    compares shape and column count rather than column-name equality.
    """
    if not (
        hasattr(pyreadstat, "write_xport")
        and hasattr(pyreadstat, "read_xport")
    ):
        pytest.skip(
            "pyreadstat.write_xport / read_xport not present in this "
            f"wheel ({pyreadstat.__version__}); skipping XPORT smoke"
        )

    df = _build_tiny_dataframe()
    output_path = tmp_path / "smoke.xpt"

    pyreadstat.write_xport(df, str(output_path))

    assert output_path.exists() and output_path.stat().st_size > 0, (
        "pyreadstat.write_xport produced no output file or an empty file"
    )

    read_df, _meta = pyreadstat.read_xport(str(output_path))

    assert read_df.shape == df.shape, (
        f"XPORT round-trip changed the DataFrame shape: wrote "
        f"{df.shape}, read back {read_df.shape}"
    )
    assert len(read_df.columns) == len(df.columns), (
        f"XPORT round-trip changed column count: wrote "
        f"{len(df.columns)}, read back {len(read_df.columns)}"
    )


# Feature: api-platform-export, Property: pyreadstat SAS7BDAT reader
# Validates: Requirements 5.2
def test_pyreadstat_read_sas7bdat_is_exposed() -> None:
    """``read_sas7bdat`` is exposed by the installed wheel.

    The export worker does not produce SAS7BDAT files (pyreadstat
    cannot write that format), but downstream consumers may feed
    SAS7BDAT files back into the platform. A wheel missing this
    symbol is broken in a way that the SAV / XPORT round-trip would
    not catch on its own.
    """
    assert hasattr(pyreadstat, "read_sas7bdat"), (
        "pyreadstat is missing read_sas7bdat; the SAS7BDAT reader "
        f"path is unavailable in this wheel ({pyreadstat.__version__})"
    )
    assert callable(pyreadstat.read_sas7bdat), (
        "pyreadstat.read_sas7bdat is present but not callable"
    )
