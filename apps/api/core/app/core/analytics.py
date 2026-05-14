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

    # Extended quality metrics (T9)
    answers_list = [r.get("answers", {}) for r in responses]
    missing_patterns = compute_missing_patterns(answers_list, questions)
    inconsistency = compute_inconsistency_scores(answers_list, questions)
    time_dist = compute_response_time_distribution(responses)
    attention = compute_attention_check_performance(answers_list, questions)

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
        # T9 extended metrics
        "missing_patterns": missing_patterns,
        "inconsistency_rate": inconsistency["inconsistency_rate"],
        "inconsistent_respondents": inconsistency["inconsistent_respondents"],
        "response_time_distribution": time_dist,
        "attention_check_pass_rate": attention["pass_rate"],
    }


# ── Text Summary (Basic) ──────────────────────────────────────────────


# ── Missing Pattern Analysis ───────────────────────────────────────────


def compute_missing_patterns(
    answers_list: list[dict],
    questions: list[dict],
) -> dict:
    """Analyze patterns in missing/omitted answers.

    Detects: per-item missing rate, per-respondent missing distribution,
    and item-pair co-missing patterns (which questions tend to be
    skipped together — may indicate problematic skip logic).

    Returns: {
        "per_item_missing": {qname: {"count": int, "rate": float}},
        "co_missing_pairs": [{"q1": str, "q2": str, "co_miss_count": int, "rate": float}],
        "respondent_distribution": [{"missing_count": int, "n_respondents": int}],
    }
    """
    n_responses = len(answers_list)
    if n_responses == 0:
        return {
            "per_item_missing": {},
            "co_missing_pairs": [],
            "respondent_distribution": [],
        }

    qnames = [q["name"] for q in questions]

    # Per-item missing
    per_item_missing: dict[str, dict] = {}
    for qname in qnames:
        missing = sum(1 for a in answers_list if a.get(qname) is None)
        per_item_missing[qname] = {
            "count": missing,
            "rate": round(missing / n_responses, 4),
        }

    # Per-respondent missing count distribution
    miss_counts: Counter = Counter()
    for ans in answers_list:
        n_miss = sum(1 for qname in qnames if ans.get(qname) is None)
        miss_counts[n_miss] += 1

    respondent_distribution = [
        {"missing_count": k, "n_respondents": v}
        for k, v in sorted(miss_counts.items())
    ]

    # Co-missing pairs (items that are both missing in the same response)
    co_missing_pairs: list[dict] = []
    for i, qa in enumerate(qnames):
        for j in range(i + 1, len(qnames)):
            qb = qnames[j]
            co_miss = sum(
                1 for a in answers_list
                if a.get(qa) is None and a.get(qb) is None
            )
            if co_miss >= 2:  # only report notable co-missing
                co_missing_pairs.append({
                    "q1": qa,
                    "q2": qb,
                    "co_miss_count": co_miss,
                    "rate": round(co_miss / n_responses, 4),
                })

    # Sort by rate descending
    co_missing_pairs.sort(key=lambda x: x["rate"], reverse=True)

    return {
        "per_item_missing": per_item_missing,
        "co_missing_pairs": co_missing_pairs[:10],  # top 10
        "respondent_distribution": respondent_distribution,
    }


# ── Inconsistency Detection ────────────────────────────────────────────


def compute_inconsistency_scores(
    answers_list: list[dict],
    questions: list[dict],
) -> dict:
    """Detect response inconsistencies — forward vs reverse-coded items.

    In a well-designed Likert scale, forward-coded and reverse-coded items
    should correlate negatively. If a respondent gives high scores to both
    a forward item and its reverse-coded counterpart, the response is
    flagged as inconsistent.

    Detects reverse-coded items by checking for "reverse" keywords in
    the question title. Compares each respondent's answers on forward
    vs reverse items and flags contradictions.

    Returns: {
        "inconsistent_respondents": int,
        "total_rate": float,
        "per_respondent_flags": [{respondent_idx, flag_count, details}, ...],
    }
    """
    # Identify forward and reverse-coded items
    forward_names: list[str] = []
    reverse_names: list[str] = []
    for q in questions:
        title = q.get("title", q.get("name", "")).lower()
        if "reverse" in title or "反向" in title or "反向计分" in title:
            reverse_names.append(q["name"])
        elif _is_likert(q):
            forward_names.append(q["name"])

    if not forward_names or not reverse_names:
        return {
            "inconsistent_respondents": 0,
            "inconsistency_rate": 0.0,
            "per_respondent_flags": [],
        }

    # Detect contradictions: high on both forward AND reverse items
    # (assuming 5+ point scale, consider 4+ as "high")
    per_respondent_flags: list[dict] = []
    inconsistent_count = 0

    for idx, ans in enumerate(answers_list):
        contradiction_count = 0
        details: list[str] = []

        for f_name in forward_names:
            f_val = ans.get(f_name)
            if f_val is None:
                continue
            try:
                f_num = float(f_val)
            except (TypeError, ValueError):
                continue

            for r_name in reverse_names:
                r_val = ans.get(r_name)
                if r_val is None:
                    continue
                try:
                    r_num = float(r_val)
                except (TypeError, ValueError):
                    continue

                # Both ≥ 4 → contradiction (reverse item should be low)
                if f_num >= 4 and r_num >= 4:
                    contradiction_count += 1
                    details.append(f"{f_name}<->{r_name}")

        if contradiction_count > 0:
            inconsistent_count += 1
            per_respondent_flags.append({
                "respondent_index": idx,
                "flag_count": contradiction_count,
                "details": details[:5],  # cap at 5
            })

    return {
        "inconsistent_respondents": inconsistent_count,
        "inconsistency_rate": round(
            inconsistent_count / len(answers_list), 4
        ) if answers_list else 0.0,
        "per_respondent_flags": per_respondent_flags[:20],  # cap at 20
    }


# ── Response Time Distribution ─────────────────────────────────────────


def compute_response_time_distribution(
    responses: list[dict],
) -> dict:
    """Analyze per-question response time distribution.

    Returns quantiles (P5/P25/P50/P75/P95), outlier identification,
    and summary statistics.

    Returns: {
        "quantiles": dict,
        "fast_threshold": float,
        "slow_threshold": float,
        "fast_respondents": int,
        "slow_respondents": int,
    }
    """
    times = [
        r.get("metadata", {}).get("completion_time_seconds", 0)
        for r in responses
        if r.get("metadata", {}).get("completion_time_seconds")
    ]

    if not times:
        return {
            "quantiles": {},
            "fast_threshold": 0.0,
            "slow_threshold": 0.0,
            "fast_respondents": 0,
            "slow_respondents": 0,
        }

    sorted_times = sorted(times)
    n = len(sorted_times)

    def _quantile(pct: float) -> float:
        idx = int(pct * (n - 1))
        return round(float(sorted_times[idx]), 1)

    p5 = _quantile(0.05)
    p95 = _quantile(0.95)
    p25 = _quantile(0.25)
    p50 = _quantile(0.50)
    p75 = _quantile(0.75)

    fast_count = sum(1 for t in times if t < p5) if p5 > 0 else 0
    slow_count = sum(1 for t in times if t > p95) if p95 > 0 else 0

    return {
        "quantiles": {
            "p5": p5,
            "p25": p25,
            "p50": p50,
            "p75": p75,
            "p95": p95,
        },
        "fast_threshold": p5,
        "slow_threshold": p95,
        "fast_respondents": fast_count,
        "slow_respondents": slow_count,
    }


# ── Attention Check Analysis ───────────────────────────────────────────


def compute_attention_check_performance(
    answers_list: list[dict],
    questions: list[dict],
) -> dict:
    """Analyze attention check items embedded in the survey.

    Attention check questions are identified by SurveyJS custom properties:
    ``isAttentionCheck: true`` in the question definition.

    Returns: {
        "attention_items": [qname, ...],
        "total_checks": int,
        "pass_count": int,
        "fail_count": int,
        "pass_rate": float,
        "failed_respondents": [index, ...],
    }
    """
    attention_items = [
        q for q in questions
        if q.get("isAttentionCheck", False)
    ]
    attention_names = [q["name"] for q in attention_items]

    if not attention_names:
        return {
            "attention_items": [],
            "total_checks": 0,
            "pass_count": 0,
            "fail_count": 0,
            "pass_rate": 0.0,
            "failed_respondents": [],
        }

    # For each attention check, the correct answer is specified
    # (e.g., "correctAnswer" or "attentionAnswer" in question metadata)
    correct_map: dict[str, str] = {}
    for q in attention_items:
        correct = q.get("correctAnswer") or q.get("attentionAnswer")
        if correct is not None:
            correct_map[q["name"]] = str(correct)

    failed_indices: list[int] = []
    total_checks = 0
    pass_count = 0
    fail_count = 0

    for idx, ans in enumerate(answers_list):
        respondent_passed = True
        for qname in attention_names:
            if qname not in correct_map:
                continue
            total_checks += 1
            val = ans.get(qname)
            if val is not None and str(val) == correct_map[qname]:
                pass_count += 1
            else:
                fail_count += 1
                respondent_passed = False
        if not respondent_passed:
            failed_indices.append(idx)

    # pass_rate based on checks, not respondents
    total = pass_count + fail_count
    pass_rate = round(pass_count / total * 100, 1) if total > 0 else 0.0

    return {
        "attention_items": attention_names,
        "total_checks": total_checks,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_rate": pass_rate,
        "failed_respondents": failed_indices[:50],  # cap at 50
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
