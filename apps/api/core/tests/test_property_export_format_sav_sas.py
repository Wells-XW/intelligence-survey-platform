"""Property tests for binary export format structural invariants.

Validates Property 14 from design.md for the two binary statistical
formats — SPSS ``.sav`` and SAS Transport ``.xpt``. These formats are
optional: their producers only load when ``pyreadstat`` imports
cleanly, so this test is gated on the same condition. The textual
half of Property 14 lives in ``test_property_export_format_invariants.py``.

The property under test — adapted from the SAV/SAS clause of Property
14 to a roundtrip-friendly form — is structural equivalence after a
write/read cycle:

    For any survey ``S`` and any list of responses ``R``, after
    materializing the export with the SAV / XPT producer and reading
    it back via ``pyreadstat.read_sav`` / ``pyreadstat.read_xport``,
    the resulting DataFrame has the same row count, the same column
    count, the same column order, and per-column dtypes that match
    the input modulo each format's coercion rules.

Format-pivot context (XPT instead of SAS7BDAT):
    The originally specified SAS path was ``.sas7bdat``, but
    ``pyreadstat`` does not expose ``write_sas7bdat`` at any released
    version (the library can read SAS7BDAT but not write it). The
    producer therefore writes SAS Transport (``.xpt``) — pyreadstat's
    ``write_xport`` is the supported SAS write path, and downstream
    SAS users import the file with ``PROC CIMPORT``.

Coercion rules each format imposes that the test honors:
    * SPSS treats every numeric column as 8-byte double precision —
      integers therefore round-trip as floats. The dtype assertion
      accepts ``kind == 'f'`` for any input numeric column.
    * SAS pads strings to a fixed width, so empty strings are
      preserved as empty strings but trailing whitespace is stripped.
      We do not assert value equality, only column-level dtype.
    * XPORT v5 caps variable names at 8 ASCII characters and
      uppercases them on write; XPORT v8 (pyreadstat's current
      default) preserves case and lifts the cap to 32 characters.
      The column-order assertion compares case-insensitively
      (``upper()`` on both sides) so the test stays correct under
      either format-version path. Generated column names are
      ``q0``..``q7`` so the v5 length cap is never approached.

``pyreadstat`` write-then-read is meaningfully slower than the
in-memory CSV / JSON producers (the on-disk binary layouts involve
multi-block headers and per-column metadata blocks), so per design
§Testing Strategy the iteration count is lowered to ``max_examples=20``
from the project default of 100.

Reference: design.md §Property 14 (binary formats) and §Testing
Strategy. Validates Requirement 5.8.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import pytest

# Skip the entire module when pyreadstat (or its pandas dep) is not
# importable — the SAV/XPT producers themselves are gated on the same
# probe and SUPPORTED_FORMATS will not advertise these formats in
# that case.
pyreadstat = pytest.importorskip("pyreadstat")
pd = pytest.importorskip("pandas")

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from app.services.export_formats.sas_producer import write_xport  # noqa: E402
from app.services.export_formats.sav_producer import write_sav  # noqa: E402


# String alphabet: printable code points only. We exclude
#   * surrogates (category ``Cs``) — invalid in any utf-8 byte stream;
#   * other control codepoints (category ``Cc``) — pyreadstat's
#     binary writer rejects NULs and behaves inconsistently across
#     platforms on other low-ASCII control bytes;
#   * the explicit NUL ``\x00`` for belt-and-braces safety on
#     Hypothesis builds where ``Cc`` filtering misses it.
# The constraint is a faithful model of real survey-response text:
# end users type printable characters, and the API layer would never
# accept a NUL-bearing answer through JSON validation anyway.
_string_alphabet = st.characters(
    blacklist_categories=("Cs", "Cc"),
    blacklist_characters=["\x00"],
)


def _safe_float() -> st.SearchStrategy[float]:
    """Generate finite, non-NaN floats representable in IEEE 754 double.

    SPSS and SAS both encode numeric values as 8-byte doubles. NaN
    and ±inf are technically valid bit patterns but they collide with
    the formats' own missing-value sentinels and trip pyreadstat's
    encoder on some platforms. Restricting to finite values keeps
    the dtype assertion focused on the structural property the
    producer is responsible for.
    """
    return st.floats(allow_nan=False, allow_infinity=False, width=64)


@st.composite
def _tabular_dataset(
    draw: st.DrawFn,
) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    """Generate a (column_names, column_dtypes, rows) tabular dataset.

    Column names follow the fixed pattern ``q0`` .. ``q7`` so they
    are guaranteed to be valid SurveyJS question names, valid Python
    identifiers, and valid SAS variable names under both XPORT v5 (8
    ASCII chars max) and XPORT v8 (32 chars max). Per-column dtype is
    one of ``"int"``, ``"float"``, ``"string"`` and is consistent
    across all rows for that column — mixed-dtype columns would be
    coerced to ``object`` by pandas and are out of scope for the
    structural property under test.
    """
    n_cols = draw(st.integers(min_value=1, max_value=8))
    col_names = [f"q{i}" for i in range(n_cols)]
    col_dtypes = draw(
        st.lists(
            st.sampled_from(["int", "float", "string"]),
            min_size=n_cols,
            max_size=n_cols,
        )
    )

    n_rows = draw(st.integers(min_value=1, max_value=20))

    rows: List[Dict[str, Any]] = []
    for _ in range(n_rows):
        row: Dict[str, Any] = {}
        for name, dtype in zip(col_names, col_dtypes):
            if dtype == "int":
                row[name] = draw(
                    st.integers(min_value=-(10**9), max_value=10**9)
                )
            elif dtype == "float":
                row[name] = draw(_safe_float())
            else:  # string
                row[name] = draw(
                    st.text(alphabet=_string_alphabet, max_size=30)
                )
        rows.append(row)

    return col_names, col_dtypes, rows


@st.composite
def _survey_with_tabular_responses(
    draw: st.DrawFn,
) -> Tuple[
    SimpleNamespace,
    List[SimpleNamespace],
    List[str],
    List[str],
]:
    """Wrap the tabular dataset in survey/response namespaces.

    The producer interface accepts ``(survey, responses, output_path)``
    where ``survey.json_content`` is a SurveyJS-shaped schema and each
    response exposes an ``answers`` dict. This composite returns those
    plus the underlying column names and dtype tags so the test
    assertions can refer to them directly.
    """
    col_names, col_dtypes, rows = draw(_tabular_dataset())
    elements = [
        {"name": n, "title": "Q", "type": "text"} for n in col_names
    ]
    survey = SimpleNamespace(
        json_content={"pages": [{"name": "page1", "elements": elements}]}
    )
    responses = [SimpleNamespace(answers=row) for row in rows]
    return survey, responses, col_names, col_dtypes


def _assert_dtype_compatible(
    column_name: str,
    expected_kind: str,
    actual_dtype: Any,
) -> None:
    """Assert ``actual_dtype`` matches ``expected_kind`` post-roundtrip.

    pyreadstat reports column dtypes via the underlying numpy dtype
    on the returned DataFrame. The mapping rules this test honors:

      * Input ``int``     → numeric column      → ``dtype.kind == 'f'``
        (SPSS / SAS store all numerics as 8-byte double; integer
        narrowing is not preserved.)
      * Input ``float``   → numeric column      → ``dtype.kind == 'f'``
      * Input ``string``  → character column    → ``dtype.kind == 'O'``
        (pandas object dtype, holding Python ``str`` values.)
    """
    kind = getattr(actual_dtype, "kind", None)
    assert kind == expected_kind, (
        f"column {column_name!r}: expected kind={expected_kind!r}, "
        f"got dtype={actual_dtype!r} (kind={kind!r})"
    )


def _expected_kind_for(dtype_tag: str) -> str:
    """Map an input dtype tag to the post-roundtrip ``dtype.kind``.

    Centralizing the mapping keeps the SAV and XPT test bodies in
    sync — both producers go through ``pyreadstat`` with the same
    pandas-DataFrame intermediate, so they share the same coercion
    rules.
    """
    if dtype_tag in ("int", "float"):
        return "f"  # numeric → double
    return "O"  # string → object


# Feature: api-platform-export, Property 14: Export format structural invariants
@given(dataset=_survey_with_tabular_responses())
@settings(max_examples=20, deadline=None)
def test_p14_sav_roundtrip_structural_equivalence(
    tmp_path_factory: Any,
    dataset: Tuple[
        SimpleNamespace,
        List[SimpleNamespace],
        List[str],
        List[str],
    ],
) -> None:
    """SPSS .sav write/read roundtrip preserves shape and dtype kind.

    Sub-invariants asserted in lock-step:
      * Row count of the read-back DataFrame equals ``len(responses)``.
      * Column count equals ``len(col_names)`` and the column order
        matches the input order; SPSS preserves the variable-order
        section of the file header verbatim.
      * Per-column dtype kind matches the format's coercion rule:
        numeric inputs (int / float) read back as float, string
        inputs read back as object.

    Validates: Requirements 5.8.
    """
    survey, responses, col_names, col_dtypes = dataset
    tmp_path: Path = tmp_path_factory.mktemp("p14_sav")
    out = tmp_path / "out.sav"

    write_sav(survey, responses, out)

    df_read, _meta = pyreadstat.read_sav(str(out))

    assert len(df_read) == len(responses), (
        f"row count mismatch: wrote {len(responses)} responses, "
        f"read back {len(df_read)} rows"
    )
    assert list(df_read.columns) == col_names, (
        f"column order mismatch: wrote {col_names}, "
        f"read back {list(df_read.columns)}"
    )
    for name, tag in zip(col_names, col_dtypes):
        _assert_dtype_compatible(
            column_name=name,
            expected_kind=_expected_kind_for(tag),
            actual_dtype=df_read[name].dtype,
        )


# Feature: api-platform-export, Property 14: Export format structural invariants
@given(dataset=_survey_with_tabular_responses())
@settings(max_examples=20, deadline=None)
def test_p14_xport_roundtrip_structural_equivalence(
    tmp_path_factory: Any,
    dataset: Tuple[
        SimpleNamespace,
        List[SimpleNamespace],
        List[str],
        List[str],
    ],
) -> None:
    """SAS .xpt write/read roundtrip preserves shape and dtype kind.

    Same structural invariants as the SAV test, applied to the SAS
    Transport (XPORT) binary format. SAS uses fixed-width string
    columns and stores every numeric as a double, so the coercion
    rules collapse to the same shape as SPSS for the dimensions this
    property cares about.

    XPORT-specific quirks honoured by the assertions:

      * Variable-name length: XPORT v5 caps names at 8 ASCII chars;
        v8 lifts the cap to 32. The dataset generator uses ``q0``..
        ``q7``, so even v5 has headroom.
      * Variable-name case: XPORT v5 uppercases names on write; v8
        preserves case. The column-order assertion uppercases both
        sides so it holds under either format-version path.

    Validates: Requirements 5.8.
    """
    survey, responses, col_names, col_dtypes = dataset
    tmp_path: Path = tmp_path_factory.mktemp("p14_xpt")
    out = tmp_path / "out.xpt"

    write_xport(survey, responses, out)

    df_read, _meta = pyreadstat.read_xport(str(out))

    assert len(df_read) == len(responses), (
        f"row count mismatch: wrote {len(responses)} responses, "
        f"read back {len(df_read)} rows"
    )

    # XPORT may uppercase column names depending on file_format_version
    # (v5 uppercases; v8 preserves case). Compare case-insensitively
    # so the assertion is robust against a future bump in pyreadstat's
    # default file_format_version.
    expected_upper = [c.upper() for c in col_names]
    actual_upper = [c.upper() for c in df_read.columns]
    assert actual_upper == expected_upper, (
        f"column order mismatch (case-insensitive): wrote "
        f"{expected_upper}, read back {actual_upper}"
    )

    # Resolve actual column name (may differ in case from input) so
    # the per-column dtype lookup works under either v5 / v8 path.
    actual_by_upper = {c.upper(): c for c in df_read.columns}
    for name, tag in zip(col_names, col_dtypes):
        actual_name = actual_by_upper[name.upper()]
        _assert_dtype_compatible(
            column_name=actual_name,
            expected_kind=_expected_kind_for(tag),
            actual_dtype=df_read[actual_name].dtype,
        )
