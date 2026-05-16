"""XLSX export producer.

Writes survey responses to a single-sheet ``.xlsx`` file using
``openpyxl``. The header row matches the survey's canonical question
order. Native primitive types (int, float, bool, str) are preserved;
complex types (list, dict) are JSON-encoded into a single string cell
because the XLSX format has no native nested-structure type.

Reference: design.md §Component 7 and Requirement 5.6.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence


def _coerce_to_xlsx(value: Any) -> Any:
    """Coerce an answer value to a type the XLSX writer accepts.

    openpyxl can persist ``str``, ``int``, ``float``, ``bool``,
    ``datetime``, and ``None`` directly. Lists and dicts are encoded
    as compact JSON strings so the cell holds a faithful textual
    representation of the original answer.

    Args:
        value: The raw answer value from ``response.answers``.

    Returns:
        A value openpyxl can write into a cell.
    """
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def write_xlsx(
    survey: Any,
    responses: Sequence[Any],
    output_path: Path,
) -> None:
    """Write responses to a single-sheet XLSX workbook.

    Args:
        survey: A Survey-like object exposing a ``json_content`` dict
            attribute holding the SurveyJS schema.
        responses: Sequence of SurveyResponse-like objects each
            exposing an ``answers`` dict attribute.
        output_path: Filesystem path the workbook will be written to.

    Raises:
        ImportError: If ``openpyxl`` is not installed.
        OSError: If the file cannot be written.
    """
    # openpyxl is heavyweight; import lazily so the module loads in
    # environments where xlsx is not actually used.
    from openpyxl import Workbook  # type: ignore[import-not-found]

    from . import canonical_question_order

    cols = canonical_question_order(getattr(survey, "json_content", {}) or {})

    wb = Workbook()
    ws = wb.active
    ws.title = "Responses"

    ws.append(cols)
    for response in responses:
        answers = getattr(response, "answers", {}) or {}
        ws.append([_coerce_to_xlsx(answers.get(c)) for c in cols])

    wb.save(str(output_path))
