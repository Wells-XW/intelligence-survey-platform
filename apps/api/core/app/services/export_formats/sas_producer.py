"""SAS sas7bdat export producer (optional, requires pyreadstat).

Writes survey responses to a SAS ``.sas7bdat`` file. The labelling
strategy is identical to the SPSS producer: variable labels come from
question titles, value labels come from choice options. The producer
is only loaded when ``pyreadstat`` imports cleanly.

Reference: design.md §Component 7 and Requirement 5.8.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence


def write_sas7bdat(
    survey: Any,
    responses: Sequence[Any],
    output_path: Path,
) -> None:
    """Write responses to a SAS ``.sas7bdat`` file.

    Args:
        survey: A Survey-like object exposing a ``json_content`` dict
            attribute holding the SurveyJS schema.
        responses: Sequence of SurveyResponse-like objects each
            exposing an ``answers`` dict attribute.
        output_path: Filesystem path the .sas7bdat file will be
            written to.

    Raises:
        ImportError: If ``pyreadstat`` or ``pandas`` are not installed.
        Exception: pyreadstat may raise its own write errors;
            propagated unchanged so the export worker can record the
            error message on the job row.
    """
    import pandas as pd  # type: ignore[import-not-found]
    import pyreadstat  # type: ignore[import-not-found]

    from . import canonical_question_order, question_metadata
    from .sav_producer import _build_value_labels, _coerce_for_dataframe

    survey_json = getattr(survey, "json_content", {}) or {}
    cols = canonical_question_order(survey_json)
    meta = question_metadata(survey_json)

    rows: List[Dict[str, Any]] = []
    for response in responses:
        answers = getattr(response, "answers", {}) or {}
        rows.append({c: _coerce_for_dataframe(answers.get(c)) for c in cols})

    df = pd.DataFrame(rows, columns=cols)

    column_labels = {c: meta[c]["title"] for c in cols if c in meta}
    variable_value_labels = _build_value_labels(cols, meta)

    pyreadstat.write_sas7bdat(
        df,
        str(output_path),
        column_labels=column_labels,
        variable_value_labels=variable_value_labels,
    )
