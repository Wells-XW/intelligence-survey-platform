"""Multi-format export producers for the survey response pipeline.

Each producer in this package writes one supported format to disk
given a survey, its responses, and an output path. The producers
share a small upstream helper :func:`canonical_question_order` that
walks the SurveyJS schema once per job to give every producer the
same column order.

Format support detection:
    ``SUPPORTED_FORMATS`` is initialized to ``{"csv", "xlsx", "json"}``
    and conditionally extended with ``{"sav", "sas7bdat"}`` when the
    ``pyreadstat`` library is importable in the worker's runtime
    environment. The route layer reads this set on every create
    request to reject unsupported formats with a 400 response per
    Req 5.3.

Reference: design.md §Component 7.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List

# Always-available producers (mandatory formats per Req 5.1).
from .csv_producer import write_csv  # noqa: F401
from .json_producer import write_json  # noqa: F401
from .xlsx_producer import write_xlsx  # noqa: F401

_BASE_FORMATS: FrozenSet[str] = frozenset({"csv", "xlsx", "json"})


def _detect_pyreadstat() -> bool:
    """Best-effort import probe for ``pyreadstat``.

    Returns:
        True if the library imports cleanly in this worker's runtime
        environment, False otherwise. Exceptions during import are
        swallowed so a missing native dependency cannot prevent the
        rest of the export subsystem from booting.
    """
    try:
        import pyreadstat  # noqa: F401
        return True
    except Exception:
        return False


_PYREADSTAT_AVAILABLE: bool = _detect_pyreadstat()

if _PYREADSTAT_AVAILABLE:
    from .sav_producer import write_sav  # noqa: F401
    from .sas_producer import write_sas7bdat  # noqa: F401
    SUPPORTED_FORMATS: FrozenSet[str] = _BASE_FORMATS | {"sav", "sas7bdat"}
else:
    SUPPORTED_FORMATS: FrozenSet[str] = _BASE_FORMATS


def canonical_question_order(survey_json: Dict[str, Any]) -> List[str]:
    """Walk the SurveyJS schema to extract the canonical question order.

    The output column order for every format is determined by this
    function so all producers render columns in lockstep. Pages are
    visited in ``pages[]`` declaration order; questions within each
    page are visited in ``elements[]`` declaration order. Question
    names that are non-strings or empty are skipped, and duplicate
    names (which SurveyJS itself rejects) are deduplicated by first
    occurrence.

    Args:
        survey_json: The survey's ``json_content`` JSONB blob.

    Returns:
        Ordered list of unique question name strings. Empty list if
        the schema is malformed or has no questions.
    """
    seen = set()
    order: List[str] = []
    if not isinstance(survey_json, dict):
        return order
    pages = survey_json.get("pages") or []
    for page in pages:
        if not isinstance(page, dict):
            continue
        elements = page.get("elements") or []
        for el in elements:
            if not isinstance(el, dict):
                continue
            name = el.get("name")
            if not isinstance(name, str) or not name:
                continue
            if name in seen:
                continue
            seen.add(name)
            order.append(name)
    return order


def question_metadata(survey_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Extract per-question metadata keyed by question name.

    Used by the SAV and SAS producers to populate variable_labels
    (the question's display title) and value_labels (the choice
    options for closed-ended questions).

    Args:
        survey_json: The survey's ``json_content`` JSONB blob.

    Returns:
        Dict keyed by question name. Each entry has keys ``title``
        (str), ``type`` (str), and ``choices`` (list, possibly empty).
    """
    meta: Dict[str, Dict[str, Any]] = {}
    if not isinstance(survey_json, dict):
        return meta
    pages = survey_json.get("pages") or []
    for page in pages:
        if not isinstance(page, dict):
            continue
        for el in page.get("elements") or []:
            if not isinstance(el, dict):
                continue
            name = el.get("name")
            if not isinstance(name, str) or not name:
                continue
            meta[name] = {
                "title": el.get("title") or name,
                "type": el.get("type", "text"),
                "choices": el.get("choices") or [],
            }
    return meta


__all__ = [
    "SUPPORTED_FORMATS",
    "canonical_question_order",
    "question_metadata",
    "write_csv",
    "write_json",
    "write_xlsx",
]
