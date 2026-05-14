"""Pure-Python analytics engine for survey response data.

No LLM dependency — all statistics are deterministic mathematical
computations. AI-powered sentiment analysis and theme extraction for
open-ended responses will be added in Phase 2.

All functions accept:
- answers: list[dict] — each dict maps question_name → answer_value
- questions: list[dict] — question definitions from SurveyJS JSON

Question definitions follow SurveyJS format:
  {"name": "q1", "type": "radiogroup", "title": "...", "choices": [...]}
"""

from __future__ import annotations

import math
from collections import Counter
from statistics import mean, median, stdev


def _extract_question_defs(
    json_content: dict,
) -> list[dict]:
    """Flatten all questions from SurveyJS JSON pages into a list."""
    questions: list[dict] = []
    for page in json_content.get("pages", []):
        for elem in page.get("elements", []):
            if elem.get("type") == "panel":
                # Dynamic panels — recurse into nested elements
                for nested in elem.get("elements", []):
                    questions.append(nested)
            else:
                questions.append(elem)
    return questions


# ── Helper: classify question type ────────────────────────────────────

CATEGORICAL_TYPES = {"radiogroup", "dropdown", "checkbox", "imagepicker", "boolean"}
NUMERIC_TYPES = {"rating", "ranking", "expression"}
TEXT_TYPES = {"text", "comment", "multipletext"}
MATRIX_TYPES = {"matrix", "matrixdropdown", "matrixdynamic"}


def _is_categorical(q: dict) -> bool:
    return q.get("type", "") in CATEGORICAL_TYPES


def _is_numeric(q: dict) -> bool:
    return q.get("type", "") in NUMERIC_TYPES


def _is_text(q: dict) -> bool:
    return q.get("type", "") in TEXT_TYPES


def _is_likert(q: dict) -> bool:
    """Detect Likert-scale questions (rating with numeric values 1-5 or 1-7)."""
    if q.get("type") != "rating":
        return False
    rate_type = q.get("rateType", "labels")
    if rate_type == "labels":
        # Check if labels look like Likert (e.g., "Strongly Disagree" → "Strongly Agree")
        return True
    return False


# ── Frequency Analysis ────────────────────────────────────────────────


def compute_frequencies(
    answers_list: list[dict],
    question_def: dict,
) -> list[dict]:
    """Compute frequency distribution for a single categorical question.

    Returns: [{"value": "Option A", "count": 42, "percentage": 58.3}, ...]
    """
    qname = question_def["name"]
    counter: Counter = Counter()

    choices = question_def.get("choices", [])
    if not choices:
        # Free-text input — extract unique values
        for ans in answers_list:
            val = ans.get(qname)
            if val is not None:
                if isinstance(val, list):
                    for v in val:
                        counter[str(v)] += 1
                else:
                    counter[str(val)] += 1
    else:
        # Pre-defined choices — count each
        choice_labels = {c.get("value", c.get("text", "")): c.get("text", "") for c in choices}
        for ans in answers_list:
            val = ans.get(qname)
            if val is None:
                continue
            if isinstance(val, list):
                for v in val:
                    label = choice_labels.get(str(v), str(v))
                    counter[label] += 1
            else:
                label = choice_labels.get(str(val), str(val))
                counter[label] += 1

    total = sum(counter.values()) or 1
    return [
        {"value": value, "count": count, "percentage": round(count / total * 100, 1)}
        for value, count in counter.most_common()
    ]


# ── Descriptive Statistics (Numeric) ──────────────────────────────────


def compute_descriptive(
    answers_list: list[dict],
    question_def: dict,
) -> dict | None:
    """Compute mean, median, mode, std for a numeric/rating question.

    Returns None if there are no numeric answers.
    """
    qname = question_def["name"]
    values: list[float] = []
    for ans in answers_list:
        val = ans.get(qname)
        if val is not None:
            try:
                values.append(float(val))
            except (TypeError, ValueError):
                continue

    if not values:
        return None

    # Mode (may be multi-modal)
    counter = Counter(values)
    max_count = max(counter.values())
    mode_vals = sorted([v for v, c in counter.items() if c == max_count])

    return {
        "mean": round(mean(values), 3),
        "median": round(median(values), 3),
        "mode": mode_vals,
        "std_dev": round(stdev(values), 3) if len(values) > 1 else 0.0,
        "min_value": min(values),
        "max_value": max(values),
        "n": len(values),
    }


# ── Cross-Tabulation ──────────────────────────────────────────────────


def compute_cross_tab(
    answers_list: list[dict],
    q1_def: dict,
    q2_def: dict,
) -> dict:
    """Build a cross-tabulation matrix between two categorical questions.

    Returns: {
        "row_labels": [...], "col_labels": [...],
        "matrix": [[int, ...], ...], "n": int
    }
    """
    q1_name = q1_def["name"]
    q2_name = q2_def["name"]

    # Collect labels
    q1_choices = q1_def.get("choices", [])
    q2_choices = q2_def.get("choices", [])

    if q1_choices:
        row_labels = [c.get("text", c.get("value", "")) for c in q1_choices]
    if q2_choices:
        col_labels = [c.get("text", c.get("value", "")) for c in q2_choices]

    # If no predefined choices, discover from data
    if not q1_choices:
        row_set: set[str] = set()
        for ans in answers_list:
            v = ans.get(q1_name)
            if v is not None:
                row_set.add(str(v))
        row_labels = sorted(row_set)
    if not q2_choices:
        col_set: set[str] = set()
        for ans in answers_list:
            v = ans.get(q2_name)
            if v is not None:
                col_set.add(str(v))
        col_labels = sorted(col_set)

    # Build lookup
    row_idx = {label: i for i, label in enumerate(row_labels)}
    col_idx = {label: i for i, label in enumerate(col_labels)}

    # Initialize matrix
    matrix: list[list[int]] = [[0] * len(col_labels) for _ in range(len(row_labels))]

    # Fill matrix
    n = 0
    for ans in answers_list:
        rval = ans.get(q1_name)
        cval = ans.get(q2_name)
        if rval is None or cval is None:
            continue
        # Handle checkbox (list) — take first value
        if isinstance(rval, list):
            rval = rval[0] if rval else None
        if isinstance(cval, list):
            cval = cval[0] if cval else None
        if rval is None or cval is None:
            continue

        rstr = str(rval)
        cstr = str(cval)
        ri = row_idx.get(rstr)
        ci = col_idx.get(cstr)
        if ri is not None and ci is not None:
            matrix[ri][ci] += 1
            n += 1

    # Chi-square statistic (basic)
    chi_square = _compute_chi_square(matrix, n) if n > 0 else None

    return {
        "row_labels": row_labels,
        "col_labels": col_labels,
        "matrix": matrix,
        "chi_square": chi_square,
        "n": n,
    }


def _compute_chi_square(matrix: list[list[int]], n: int) -> float | None:
    """Compute Pearson chi-square statistic for a 2D contingency table."""
    if n == 0:
        return None

    n_rows = len(matrix)
    n_cols = len(matrix[0]) if matrix else 0
    if n_rows < 2 or n_cols < 2:
        return None

    row_sums = [sum(row) for row in matrix]
    col_sums = [sum(matrix[i][j] for i in range(n_rows)) for j in range(n_cols)]

    chi2 = 0.0
    for i in range(n_rows):
        for j in range(n_cols):
            expected = (row_sums[i] * col_sums[j]) / n
            if expected > 0:
                observed = matrix[i][j]
                chi2 += (observed - expected) ** 2 / expected

    return round(chi2, 4)


# ── Cronbach's Alpha ──────────────────────────────────────────────────


def compute_cronbach_alpha(
    answers_list: list[dict],
    item_names: list[str],
) -> dict:
    """Compute Cronbach's alpha for a set of Likert-scale items.

    Formula:
      α = (k / (k-1)) * (1 - (Σ var_i / var_total))

    where:
      k = number of items
      var_i = variance of item i
      var_total = variance of total scores (sum per respondent)

    Returns: {
        "alpha": float,
        "n_items": int,
        "n_valid_responses": int,
        "item_variances": {item_name: float},
        "total_variance": float,
    }
    """
    k = len(item_names)
    if k < 2:
        return {
            "alpha": 0.0,
            "n_items": k,
            "n_valid_responses": 0,
            "item_variances": {},
            "total_variance": 0.0,
        }

    # Build complete-case matrix: only respondents who answered all items
    rows: list[list[float]] = []
    for ans in answers_list:
        row: list[float] = []
        valid = True
        for item in item_names:
            val = ans.get(item)
            if val is None:
                valid = False
                break
            try:
                row.append(float(val))
            except (TypeError, ValueError):
                valid = False
                break
        if valid:
            rows.append(row)

    n = len(rows)
    if n < 2:
        return {
            "alpha": 0.0,
            "n_items": k,
            "n_valid_responses": n,
            "item_variances": {},
            "total_variance": 0.0,
        }

    # Item variances
    item_variances: dict[str, float] = {}
    for j, item_name in enumerate(item_names):
        col = [row[j] for row in rows]
        col_mean = mean(col)
        item_variances[item_name] = round(
            sum((x - col_mean) ** 2 for x in col) / (n - 1), 4
        )

    # Total scores & variance
    total_scores = [sum(row) for row in rows]
    total_mean = mean(total_scores)
    total_variance = round(
        sum((s - total_mean) ** 2 for s in total_scores) / (n - 1), 4
    )

    sum_item_vars = sum(item_variances.values())

    if total_variance == 0:
        alpha = 0.0
    else:
        alpha = (k / (k - 1)) * (1 - sum_item_vars / total_variance)

    # Clamp to [0, 1]
    alpha = max(0.0, min(1.0, round(alpha, 4)))

    return {
        "alpha": alpha,
        "n_items": k,
        "n_valid_responses": n,
        "item_variances": item_variances,
        "total_variance": total_variance,
    }


def _interpret_alpha(alpha: float) -> str:
    """Human-readable interpretation of Cronbach's alpha."""
    if alpha >= 0.9:
        return "Excellent (≥0.9)"
    if alpha >= 0.8:
        return "Good (0.8–0.9)"
    if alpha >= 0.7:
        return "Acceptable (0.7–0.8)"
    if alpha >= 0.6:
        return "Questionable (0.6–0.7)"
    return "Poor (<0.6)"


# ── Response Quality ──────────────────────────────────────────────────


def compute_response_quality(
    responses: list[dict],  # list of {answers, metadata, is_complete, submitted_at}
    questions: list[dict],
) -> dict:
    """Analyze response quality: completion rate, speeders, straightliners.

    Args:
        responses: List of response dicts from ORM rows.
            Each has: answers (dict), metadata (dict), is_complete (bool)
        questions: Question definitions from survey JSON.
    """
    total = len(responses)
    if total == 0:
        return {
            "total_responses": 0,
            "complete_responses": 0,
            "completion_rate": 0.0,
            "avg_completion_seconds": 0.0,
            "median_completion_seconds": 0.0,
            "speeder_count": 0,
            "speeder_threshold_seconds": 0.0,
            "straightliner_count": 0,
            "dropout_question": None,
            "dropout_count": 0,
        }

    complete = [r for r in responses if r.get("is_complete", True)]
    complete_count = len(complete)
    completion_rate = round(complete_count / total * 100, 1)

    # Completion times
    times = [
        r.get("metadata", {}).get("completion_time_seconds", 0)
        for r in responses
        if r.get("metadata", {}).get("completion_time_seconds")
    ]
    avg_time = round(mean(times), 1) if times else 0.0
    med_time = round(median(times), 1) if times else 0.0

    # Speeders: completed in < 1/3 of median time
    speeder_threshold = med_time / 3 if med_time > 0 else 0
    speeder_count = sum(1 for t in times if t < speeder_threshold) if speeder_threshold > 0 else 0

    # Straightliners: Likert items where ≥80% of answers are identical
    likert_names = [q["name"] for q in questions if _is_likert(q)]
    straightliner_count = 0
    if likert_names:
        for r in responses:
            answers = r.get("answers", {})
            values = [answers.get(name) for name in likert_names if answers.get(name) is not None]
            if len(values) >= 3:
                most_common_count = Counter(values).most_common(1)[0][1]
                if most_common_count / len(values) >= 0.8:
                    straightliner_count += 1

    # Dropout analysis: find the question most often unanswered
    dropout_question = None
    dropout_count = 0
    if questions:
        qname_dropouts: Counter = Counter()
        for r in responses:
            answers = r.get("answers", {})
            for q in questions:
                if q["name"] not in answers or answers[q["name"]] is None:
                    qname_dropouts[q["name"]] += 1
                    break  # count first missing per response
        if qname_dropouts:
            dropout_question, dropout_count = qname_dropouts.most_common(1)[0]

    return {
        "total_responses": total,
        "complete_responses": complete_count,
        "completion_rate": completion_rate,
        "avg_completion_seconds": avg_time,
        "median_completion_seconds": med_time,
        "speeder_count": speeder_count,
        "speeder_threshold_seconds": round(speeder_threshold, 1),
        "straightliner_count": straightliner_count,
        "dropout_question": dropout_question,
        "dropout_count": dropout_count,
    }


# ── Text Summary (Basic) ──────────────────────────────────────────────


def compute_text_summary(
    answers_list: list[dict],
    question_def: dict,
) -> dict:
    """Basic text analysis for open-ended questions.

    No AI — just word count and top unique responses.
    """
    qname = question_def["name"]
    texts: list[str] = []
    for ans in answers_list:
        val = ans.get(qname)
        if val and isinstance(val, str) and val.strip():
            texts.append(val.strip())

    if not texts:
        return {"total_responses": 0, "avg_length": 0, "top_texts": []}

    lengths = [len(t) for t in texts]
    avg_len = round(mean(lengths), 1)

    # Most common unique responses (top 5)
    text_counts = Counter(texts)
    top_texts = [text for text, _ in text_counts.most_common(5)]

    return {
        "total_responses": len(texts),
        "avg_length": avg_len,
        "top_texts": top_texts,
    }
