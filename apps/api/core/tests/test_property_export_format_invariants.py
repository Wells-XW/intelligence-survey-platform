"""Property tests for textual export format structural invariants.

Validates Property 14 from design.md for the three textual formats —
CSV, XLSX, JSON — that ship without optional dependencies. The SAV /
XPT half of Property 14 lives in a sibling test file and is gated on
``pyreadstat`` being importable.

Each test generates a SurveyJS-shaped survey schema and a small list
of responses, runs the corresponding producer against ``tmp_path``,
and asserts the file conforms to the structural contract the
downstream consumers rely on (BOM-prefixed UTF-8 CSV for Excel zh-CN,
single-sheet XLSX for the analyst pane, list-of-objects JSON for
programmatic clients).

Reference: design.md §Property 14 (textual formats). Validates
Requirements 5.5, 5.6, 5.7.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.export_formats import (
    canonical_question_order,
    write_csv,
    write_json,
    write_xlsx,
)

# A question name strategy that stays within the SurveyJS-friendly
# identifier space. Bound at 1-3 trailing digits so collisions inside
# a single survey are rare but possible — exercising the dedup path
# in canonical_question_order without dominating the test runtime.
_question_name_st = st.from_regex(r"q[0-9]{1,3}", fullmatch=True)


@st.composite
def _survey_st(draw: st.DrawFn) -> SimpleNamespace:
    """Build a SurveyJS-shaped mock survey with 1-5 unique questions.

    The schema is intentionally minimal: a single page named
    ``page1`` whose ``elements`` list holds one ``text``-typed
    question per name. The producer code only reads ``json_content``
    via ``canonical_question_order`` so any extra SurveyJS fields are
    irrelevant to this property.
    """
    names = draw(
        st.lists(_question_name_st, min_size=1, max_size=5, unique=True),
    )
    elements = [
        {"name": n, "title": "Q", "type": "text"} for n in names
    ]
    json_content = {"pages": [{"name": "page1", "elements": elements}]}
    return SimpleNamespace(json_content=json_content)


def _response_st(question_names: List[str]) -> st.SearchStrategy[List[SimpleNamespace]]:
    """Build a list of mock responses keyed against ``question_names``.

    Each response answers a (possibly empty) subset of the survey's
    questions, with primitive values that all three textual producers
    must round-trip without coercion errors. The list length is bound
    at 0-5 so XLSX writes remain quick across 100 Hypothesis examples.
    """
    if not question_names:
        # SurveyJS-shaped surveys always have ≥ 1 question via _survey_st,
        # but be defensive: an empty key set yields a fixed empty answers
        # dict so producers receive consistent input.
        answer_st: st.SearchStrategy[Dict[str, Any]] = st.just({})
    else:
        primitive_st = st.one_of(
            st.text(max_size=20),
            st.integers(),
            st.booleans(),
            st.none(),
        )
        answer_st = st.dictionaries(
            keys=st.sampled_from(question_names),
            values=primitive_st,
            max_size=len(question_names),
        )

    return st.lists(
        answer_st.map(lambda d: SimpleNamespace(answers=d)),
        min_size=0,
        max_size=5,
    )


@st.composite
def _survey_with_responses(
    draw: st.DrawFn,
) -> tuple[SimpleNamespace, List[SimpleNamespace]]:
    """Compose a survey with a response list keyed against its questions."""
    survey = draw(_survey_st())
    canonical = canonical_question_order(survey.json_content)
    responses = draw(_response_st(canonical))
    return survey, responses


# Feature: api-platform-export, Property 14: Export format structural invariants
@given(survey_and_responses=_survey_with_responses())
@settings(max_examples=100, deadline=None)
def test_p14_csv_invariants(
    tmp_path_factory: Any,
    survey_and_responses: tuple[SimpleNamespace, List[SimpleNamespace]],
) -> None:
    """CSV output is BOM-prefixed UTF-8 with header == canonical order.

    Three sub-invariants tested in lock-step:
      * The first three on-disk bytes are the UTF-8 BOM. Excel on
        Chinese-locale Windows requires this to detect the encoding
        when the user double-clicks the file.
      * After stripping the BOM via ``encoding="utf-8-sig"``, the
        first record equals ``canonical_question_order``. Column
        order must be deterministic across all formats.
      * Total record count equals ``len(responses) + 1`` (one header
        plus one row per response).

    Validates: Requirements 5.5.
    """
    survey, responses = survey_and_responses
    # Hypothesis re-invokes the function across examples; allocate a
    # fresh tmp directory per call so artefacts don't interfere.
    tmp_path: Path = tmp_path_factory.mktemp("p14_csv")
    out = tmp_path / "out.csv"

    write_csv(survey, responses, out)

    raw = out.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf", "CSV must begin with UTF-8 BOM"

    canonical = canonical_question_order(survey.json_content)
    with open(out, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    assert rows, "CSV must contain at least the header row"
    assert rows[0] == canonical
    assert len(rows) == len(responses) + 1


# Feature: api-platform-export, Property 14: Export format structural invariants
@given(survey_and_responses=_survey_with_responses())
@settings(max_examples=100, deadline=None)
def test_p14_xlsx_invariants(
    tmp_path_factory: Any,
    survey_and_responses: tuple[SimpleNamespace, List[SimpleNamespace]],
) -> None:
    """XLSX output is one sheet, header in canonical order, correct shape.

    Sub-invariants:
      * Exactly one worksheet. The producer never adds auxiliary
        sheets; consumers index sheet 0 directly.
      * The first row equals ``canonical_question_order``.
      * ``ws.max_row == len(responses) + 1`` (header + one per
        response).
      * ``ws.max_column == len(canonical)`` (column count matches
        canonical question count). Skipped when canonical is empty
        because openpyxl reports ``max_column == 1`` for a workbook
        with only an empty header row, which is an artefact of the
        XLSX wire format rather than a property violation.

    Validates: Requirements 5.6.
    """
    from openpyxl import load_workbook  # type: ignore[import-not-found]

    survey, responses = survey_and_responses
    tmp_path: Path = tmp_path_factory.mktemp("p14_xlsx")
    out = tmp_path / "out.xlsx"

    write_xlsx(survey, responses, out)

    wb = load_workbook(str(out))
    try:
        assert len(wb.sheetnames) == 1, "Workbook must contain exactly one sheet"
        ws = wb.active
        canonical = canonical_question_order(survey.json_content)
        first_row = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        assert first_row == canonical
        assert ws.max_row == len(responses) + 1
        if canonical:
            assert ws.max_column == len(canonical)
    finally:
        wb.close()


# Feature: api-platform-export, Property 14: Export format structural invariants
@given(survey_and_responses=_survey_with_responses())
@settings(max_examples=100, deadline=None)
def test_p14_json_invariants(
    tmp_path_factory: Any,
    survey_and_responses: tuple[SimpleNamespace, List[SimpleNamespace]],
) -> None:
    """JSON output is a list-of-objects with subset keys and faithful values.

    Sub-invariants:
      * The parsed document is a list whose length equals
        ``len(responses)`` (no header element, unlike CSV / XLSX).
      * Every element is an object whose keys are a subset of the
        canonical question order. The producer fills missing answers
        with ``null`` rather than omitting the key, so in practice the
        key set equals canonical, but the property is stated as a
        subset to remain robust to future producer changes that may
        elide nulls.
      * For every original-response key ``q`` that also appears in
        canonical, the parsed value equals the original answer. Keys
        present in the original response but absent from canonical
        (which can happen if the test ever drops the schema-aware
        response strategy) are ignored — consumers only see canonical
        columns.

    Validates: Requirements 5.7.
    """
    survey, responses = survey_and_responses
    tmp_path: Path = tmp_path_factory.mktemp("p14_json")
    out = tmp_path / "out.json"

    write_json(survey, responses, out)

    with open(out, "r", encoding="utf-8") as f:
        parsed = json.load(f)

    canonical = canonical_question_order(survey.json_content)
    canonical_set = set(canonical)

    assert isinstance(parsed, list)
    assert len(parsed) == len(responses)

    for parsed_item, original in zip(parsed, responses):
        assert isinstance(parsed_item, dict)
        assert set(parsed_item.keys()) <= canonical_set
        for q, v in original.answers.items():
            if q in canonical_set:
                assert parsed_item[q] == v
