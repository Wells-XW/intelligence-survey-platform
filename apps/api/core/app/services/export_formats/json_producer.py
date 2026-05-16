"""JSON export producer.

Writes survey responses as a top-level array, where each element is a
JSON object keyed by question name. The keys for every object are the
canonical question order from the SurveyJS schema; missing answers
are emitted as ``null`` so consumers can rely on a stable shape.

Reference: design.md §Component 7 and Requirement 5.7.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence


def write_json(
    survey: Any,
    responses: Sequence[Any],
    output_path: Path,
) -> None:
    """Write responses to a JSON array file.

    Args:
        survey: A Survey-like object exposing a ``json_content`` dict
            attribute holding the SurveyJS schema.
        responses: Sequence of SurveyResponse-like objects each
            exposing an ``answers`` dict attribute.
        output_path: Filesystem path the JSON file will be written to.

    Raises:
        OSError: If the file cannot be written.

    Notes:
        ``ensure_ascii=False`` preserves Chinese characters as-is.
        ``indent=2`` matches the design's pretty-printing requirement
        so the output is human-readable without post-processing.
    """
    from . import canonical_question_order

    cols = canonical_question_order(getattr(survey, "json_content", {}) or {})

    data = []
    for response in responses:
        answers = getattr(response, "answers", {}) or {}
        data.append({c: answers.get(c) for c in cols})

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
