"""SPSS .sav export producer (optional, requires pyreadstat).

Writes survey responses to an IBM SPSS ``.sav`` file with variable
labels populated from the SurveyJS question titles and value labels
populated from the choice options of closed-ended questions. This
producer is only loaded when ``pyreadstat`` imports cleanly; the
package's ``__init__`` guards the import.

Reference: design.md §Component 7 and Requirement 5.8.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence


def _build_value_labels(
    cols: List[str],
    meta: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[Any, str]]:
    """Build pyreadstat ``variable_value_labels`` from question metadata.

    SurveyJS choice arrays come in two shapes:

    * ``["a", "b", "c"]`` — string choices where value equals text.
    * ``[{"value": 1, "text": "Yes"}, ...]`` — dict choices with
      explicit value and text.

    Both shapes are normalised into ``{value: text}`` dicts. Questions
    with no choices are omitted from the result.

    Args:
        cols: Canonical question order — limits output to columns
            actually present in the dataframe.
        meta: Output of :func:`question_metadata`.

    Returns:
        Mapping from question name to ``{value: label}`` dict.
    """
    labels: Dict[str, Dict[Any, str]] = {}
    for name in cols:
        entry = meta.get(name)
        if not entry:
            continue
        choices = entry.get("choices") or []
        if not choices:
            continue
        mapping: Dict[Any, str] = {}
        for ch in choices:
            if isinstance(ch, dict):
                value = ch.get("value")
                text = ch.get("text") or (str(value) if value is not None else "")
                if value is None:
                    continue
                mapping[value] = str(text)
            elif isinstance(ch, (str, int, float)):
                mapping[ch] = str(ch)
        if mapping:
            labels[name] = mapping
    return labels


def _coerce_for_dataframe(value: Any) -> Any:
    """Coerce an answer value to a pandas/pyreadstat-friendly scalar.

    Lists and dicts are JSON-encoded so the column dtype stays
    homogeneous; primitives pass through unchanged.

    Args:
        value: Raw answer value.

    Returns:
        A scalar suitable for a pandas DataFrame column.
    """
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def write_sav(
    survey: Any,
    responses: Sequence[Any],
    output_path: Path,
) -> None:
    """Write responses to an SPSS ``.sav`` file.

    Args:
        survey: A Survey-like object exposing a ``json_content`` dict
            attribute holding the SurveyJS schema.
        responses: Sequence of SurveyResponse-like objects each
            exposing an ``answers`` dict attribute.
        output_path: Filesystem path the .sav file will be written to.

    Raises:
        ImportError: If ``pyreadstat`` or ``pandas`` are not installed.
        Exception: pyreadstat may raise its own write errors;
            propagated unchanged so the export worker can record the
            error message on the job row.
    """
    import pandas as pd  # type: ignore[import-not-found]
    import pyreadstat  # type: ignore[import-not-found]

    from . import canonical_question_order, question_metadata

    survey_json = getattr(survey, "json_content", {}) or {}
    cols = canonical_question_order(survey_json)
    meta = question_metadata(survey_json)

    rows: List[Dict[str, Any]] = []
    for response in responses:
        answers = getattr(response, "answers", {}) or {}
        rows.append({c: _coerce_for_dataframe(answers.get(c)) for c in cols})

    # Construct the dataframe with explicit columns so an empty
    # response set still has the correct schema.
    df = pd.DataFrame(rows, columns=cols)

    column_labels = {c: meta[c]["title"] for c in cols if c in meta}
    variable_value_labels = _build_value_labels(cols, meta)

    pyreadstat.write_sav(
        df,
        str(output_path),
        column_labels=column_labels,
        variable_value_labels=variable_value_labels,
    )
