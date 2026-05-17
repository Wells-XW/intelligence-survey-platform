"""SAS XPORT (.xpt) export producer (optional, requires pyreadstat).

Writes survey responses to a SAS Transport (XPT) file. The labelling
strategy mirrors the SPSS producer: variable labels come from question
titles. Value labels are not embedded because the SAS XPORT format
itself has no value-label section — the SAV producer keeps that
behaviour for SPSS, but XPORT consumers materialise value labels via
a sibling format catalog. The producer is only loaded when
``pyreadstat`` imports cleanly.

Format choice rationale:
    The originally specified ``.sas7bdat`` format is unreachable: the
    installed ``pyreadstat`` wheel (and the upstream library at every
    released version) exposes ``read_sas7bdat`` but not
    ``write_sas7bdat``. SAS Transport is the supported write path —
    downstream SAS users import the file with ``PROC CIMPORT``.

Variable name constraints:
    XPORT v5 caps variable names at 8 ASCII characters and uppercases
    them on write. XPORT v8 (pyreadstat's current default) lifts the
    cap to 32 characters and preserves case. The platform's question
    canonical order today is short ASCII identifiers (``q0`` style),
    so neither limit bites; if a future caller passes longer names
    pyreadstat will raise its own validation error and the worker
    will record it on the failed job row.

Reference: design.md §Component 7 and Requirement 5.8.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence


def write_xport(
    survey: Any,
    responses: Sequence[Any],
    output_path: Path,
) -> None:
    """Write responses to a SAS XPORT (``.xpt``) file.

    Args:
        survey: A Survey-like object exposing a ``json_content`` dict
            attribute holding the SurveyJS schema.
        responses: Sequence of SurveyResponse-like objects each
            exposing an ``answers`` dict attribute.
        output_path: Filesystem path the .xpt file will be written to.

    Raises:
        ImportError: If ``pyreadstat`` or ``pandas`` are not installed.
        Exception: pyreadstat may raise its own write errors
            (variable-name length, unsupported dtypes, etc.);
            propagated unchanged so the export worker can record the
            error message on the job row.
    """
    import pandas as pd  # type: ignore[import-not-found]
    import pyreadstat  # type: ignore[import-not-found]

    from . import canonical_question_order, question_metadata
    from .sav_producer import _coerce_for_dataframe

    survey_json = getattr(survey, "json_content", {}) or {}
    cols = canonical_question_order(survey_json)
    meta = question_metadata(survey_json)

    rows: List[Dict[str, Any]] = []
    for response in responses:
        answers = getattr(response, "answers", {}) or {}
        rows.append({c: _coerce_for_dataframe(answers.get(c)) for c in cols})

    df = pd.DataFrame(rows, columns=cols)

    column_labels = {c: meta[c]["title"] for c in cols if c in meta}

    # XPORT files have no value-label section. We omit
    # ``variable_value_labels`` rather than synthesise a sibling
    # catalog: SPSS receivers already get full label support via the
    # SAV producer, and SAS receivers materialise value labels via
    # PROC FORMAT CNTLIN downstream of the import.
    pyreadstat.write_xport(
        df,
        str(output_path),
        column_labels=column_labels,
    )
