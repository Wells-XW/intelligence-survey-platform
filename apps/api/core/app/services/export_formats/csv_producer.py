"""CSV export producer.

Writes survey responses to a UTF-8 CSV file with a leading byte order
mark (BOM) so Microsoft Excel detects the encoding correctly when the
file is opened on a Chinese-locale Windows machine. The header row
matches the survey's canonical question order; each subsequent row
contains one response, columns aligned to the header.

Reference: design.md §Component 7 and Requirement 5.5.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Sequence


# Strip C0 control characters except TAB (0x09), LF (0x0A), and CR (0x0D).
# These bytes are not legal in CSV cells consumed by Excel, LibreOffice, or
# Python's own ``csv.reader`` (which raises ``_csv.Error: line contains NUL``
# on NUL bytes). Survey respondents occasionally paste content from rich-text
# editors that smuggles in stray control bytes; sanitising them here keeps
# every textual export round-trippable. The set is the W3C XML 1.0 §2.2
# illegal-control-character range minus the three whitespace characters
# spreadsheets actually need.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _stringify(value: Any) -> str:
    """Convert an answer value to a CSV-safe string.

    Primitives stringify directly. Lists and dicts (e.g. checkbox
    arrays, matrix answers) are JSON-encoded with ``ensure_ascii=False``
    so Chinese characters survive round-trip. ``None`` becomes an
    empty string. Stray C0 control bytes (NUL through 0x1F minus
    TAB/LF/CR) are stripped because they are illegal in cells consumed
    by Excel, LibreOffice, and Python's own ``csv.reader``.

    Args:
        value: The raw answer value from ``response.answers``.

    Returns:
        A string suitable for writing to a CSV cell.
    """
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    # Sanitise control chars after coercion so the rule applies uniformly
    # to plain strings, JSON-encoded structures, and ``str(...)``-coerced
    # values alike.
    return _CONTROL_CHARS_RE.sub("", text)


def write_csv(
    survey: Any,
    responses: Sequence[Any],
    output_path: Path,
) -> None:
    """Write responses to a UTF-8-with-BOM CSV file.

    Args:
        survey: A Survey-like object exposing a ``json_content`` dict
            attribute holding the SurveyJS schema.
        responses: Sequence of SurveyResponse-like objects each
            exposing an ``answers`` dict attribute keyed by question
            name.
        output_path: Filesystem path the CSV will be written to. Any
            parent directory must already exist (the export worker
            creates the job directory before invoking the producer).

    Raises:
        OSError: If the file cannot be opened or written.

    Notes:
        The file is opened with ``encoding="utf-8-sig"`` which causes
        Python's text layer to emit ``\\ufeff`` automatically. The
        ``newline=""`` argument is required by the ``csv`` module on
        all platforms to prevent double line endings.
    """
    # Local import keeps the module importable without the app's
    # ORM machinery loaded (helps unit tests that pass mocks).
    from . import canonical_question_order

    cols = canonical_question_order(getattr(survey, "json_content", {}) or {})

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        for response in responses:
            answers = getattr(response, "answers", {}) or {}
            writer.writerow([_stringify(answers.get(c)) for c in cols])
