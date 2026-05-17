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
import re
from pathlib import Path
from typing import Any, Sequence


# Strip C0 control characters except TAB (0x09), LF (0x0A), and CR (0x0D).
# openpyxl raises ``IllegalCharacterError`` on any other byte in this range
# because the XLSX wire format embeds cell text inside XML and the W3C XML
# 1.0 §2.2 spec forbids these bytes outright. Survey respondents
# occasionally paste content from rich-text editors that smuggles in stray
# control bytes; sanitising them here keeps the export workable.
# Mirrors the equivalent sanitiser in ``csv_producer._stringify``.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _coerce_to_xlsx(value: Any) -> Any:
    """Coerce an answer value to a type the XLSX writer accepts.

    openpyxl can persist ``str``, ``int``, ``float``, ``bool``,
    ``datetime``, and ``None`` directly, but rejects strings that
    contain XML-illegal control characters with
    :class:`openpyxl.utils.exceptions.IllegalCharacterError`. Lists
    and dicts are encoded as compact JSON strings so the cell holds a
    faithful textual representation of the original answer; any string
    output is then run through :data:`_CONTROL_CHARS_RE` to strip the
    illegal bytes.

    ``None`` is converted to an empty string rather than left as
    ``None``: an entirely-``None`` row is dropped by the XLSX wire
    format on save (``ws.max_row`` collapses to the last non-empty
    row), which would silently lose responses whose answer dict is
    empty or whose every answered question lies outside the canonical
    column set. Writing ``""`` materialises the row so reload sees the
    correct ``len(responses) + 1`` row count.

    Args:
        value: The raw answer value from ``response.answers``.

    Returns:
        A value openpyxl can write into a cell.
    """
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return _CONTROL_CHARS_RE.sub(
            "",
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        )
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return _CONTROL_CHARS_RE.sub("", value)
    return _CONTROL_CHARS_RE.sub("", str(value))


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
