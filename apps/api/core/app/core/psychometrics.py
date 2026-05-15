"""Pure-Python psychometrics engine for measurement toolkit.

No LLM dependency — all computations are deterministic mathematical
formulas. Extends the analytics engine with advanced psychometric methods:

- Split-half reliability (Spearman-Brown prophecy formula)
- Corrected item-total correlations
- KMO / Bartlett's test of sphericity (factor analysis suitability)
- Multi-construct psychometrics

Uses numpy for matrix operations and scipy for Bartlett's chi-square test.
"""

from __future__ import annotations

import math

import numpy as np


# ═══════════════════════════════════════════════════════════════════════════
# Split-Half Reliability
# ═══════════════════════════════════════════════════════════════════════════


def compute_split_half_reliability(
    answers_list: list[dict],
    item_names: list[str],
    method: str = "odd_even",
) -> dict:
    """Compute split-half reliability with Spearman-Brown correction.

    Splits items into two halves, computes the correlation between total
    scores of each half, then applies the Spearman-Brown prophecy formula
    to estimate reliability for the full-length scale.

    Args:
        answers_list: List of answer dicts (question_name -> numeric value).
        item_names: Ordered list of item question names.
        method: Split method — "odd_even" (default) or "first_second".

    Returns:
        Dict with spearman_brown, split_half_r, method, halves, and n_valid.
    """
    n_items = len(item_names)
    if n_items < 2:
        return {
            "spearman_brown": None,
            "split_half_r": None,
            "method": method,
            "half1_items": item_names,
            "half2_items": [],
            "n_valid": 0,
            "interpretation": "需要至少 2 个题项才能计算分半信度",
            "error": "too_few_items",
        }

    # Split items
    if method == "odd_even":
        half1 = [item_names[i] for i in range(0, n_items, 2)]
        half2 = [item_names[i] for i in range(1, n_items, 2)]
    elif method == "first_second":
        mid = n_items // 2
        half1 = item_names[:mid]
        half2 = item_names[mid:]
    else:
        half1 = [item_names[i] for i in range(0, n_items, 2)]
        half2 = [item_names[i] for i in range(1, n_items, 2)]

    if not half2:
        half2 = half1  # single-item degenerate case

    # Build half scores (complete cases only)
    half1_scores: list[float] = []
    half2_scores: list[float] = []
    for answers in answers_list:
        vals1 = [_safe_float(answers.get(name)) for name in half1]
        vals2 = [_safe_float(answers.get(name)) for name in half2]
        if None in vals1 or None in vals2:
            continue
        half1_scores.append(sum(v for v in vals1 if v is not None))
        half2_scores.append(sum(v for v in vals2 if v is not None))

    n_valid = len(half1_scores)
    if n_valid < 3:
        return {
            "spearman_brown": None,
            "split_half_r": None,
            "method": method,
            "half1_items": half1,
            "half2_items": half2,
            "n_valid": n_valid,
            "interpretation": "有效回答数量不足（需要至少 3 份完整回答）",
            "error": "insufficient_data",
        }

    # Pearson correlation between half scores
    r = _pearson_r(half1_scores, half2_scores)
    if r is None:
        return {
            "spearman_brown": 0.0,
            "split_half_r": 0.0,
            "method": method,
            "half1_items": half1,
            "half2_items": half2,
            "n_valid": n_valid,
            "interpretation": "分半相关系数为零（数据无方差）",
        }

    # Spearman-Brown prophecy formula
    sb = (2.0 * r) / (1.0 + r) if r < 1.0 else 1.0
    sb = max(0.0, min(1.0, sb))

    if sb >= 0.9:
        interp = "优秀"
    elif sb >= 0.8:
        interp = "良好"
    elif sb >= 0.7:
        interp = "可接受"
    elif sb >= 0.6:
        interp = "存疑"
    else:
        interp = "较差"

    return {
        "spearman_brown": round(sb, 4),
        "split_half_r": round(r, 4),
        "method": method,
        "half1_items": half1,
        "half2_items": half2,
        "n_valid": n_valid,
        "interpretation": interp,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Item-Total Correlations
# ═══════════════════════════════════════════════════════════════════════════


def compute_item_total_correlations(
    answers_list: list[dict],
    item_names: list[str],
) -> dict:
    """Compute corrected item-total correlations and alpha-if-deleted.

    For each item, computes:
    1. Corrected item-total correlation (r between item and sum of all OTHER items)
    2. Cronbach's alpha if this item were removed

    Args:
        answers_list: List of answer dicts.
        item_names: List of item question names.

    Returns:
        Dict with per-item statistics and interpretation.
    """
    n_items = len(item_names)
    if n_items < 2:
        return {"items": [], "n_valid": 0, "error": "too_few_items"}

    # Build complete-case matrix
    matrix, valid_indices = _build_item_matrix(answers_list, item_names)
    n_valid = len(valid_indices)
    if n_valid < 3:
        return {"items": [], "n_valid": n_valid, "error": "insufficient_data"}

    # Compute total scores
    total_scores = np.sum(matrix, axis=1)  # shape (n_valid,)

    items = []
    for idx, name in enumerate(item_names):
        item_scores = matrix[:, idx]
        # Corrected: sum of all OTHER items
        other_sum = total_scores - item_scores

        # Item-total correlation
        corrected_r = _pearson_r_np(item_scores, other_sum)
        if corrected_r is None:
            corrected_r = 0.0

        # Alpha if deleted
        other_items = [item_names[j] for j in range(n_items) if j != idx]
        alpha_del = _compute_cronbach_alpha_from_matrix(
            np.delete(matrix, idx, axis=1), other_items
        )

        if corrected_r >= 0.4:
            flag = "good"
        elif corrected_r >= 0.2:
            flag = "moderate"
        else:
            flag = "weak"

        items.append({
            "item_name": name,
            "corrected_item_total_r": round(corrected_r, 4),
            "alpha_if_deleted": round(alpha_del, 4) if alpha_del is not None else None,
            "flag": flag,
        })

    return {"items": items, "n_valid": n_valid}


# ═══════════════════════════════════════════════════════════════════════════
# KMO & Bartlett's Test
# ═══════════════════════════════════════════════════════════════════════════


def compute_kmo_bartlett(
    answers_list: list[dict],
    item_names: list[str],
) -> dict:
    """Compute Kaiser-Meyer-Olkin (KMO) and Bartlett's test of sphericity.

    KMO measures sampling adequacy for factor analysis.
    Bartlett's test tests whether the correlation matrix is significantly
    different from an identity matrix.

    Args:
        answers_list: List of answer dicts.
        item_names: List of item question names.

    Returns:
        Dict with kmo_overall, kmo_per_item, bartlett_chi_square, bartlett_df,
        bartlett_p_value, and interpretation.
    """
    n_items = len(item_names)
    if n_items < 3:
        return {
            "kmo_overall": None,
            "kmo_per_item": {},
            "bartlett_chi_square": None,
            "bartlett_df": None,
            "bartlett_p_value": None,
            "n_valid": 0,
            "interpretation": "需要至少 3 个题项进行 KMO 和 Bartlett 检验",
            "error": "too_few_items",
        }

    # Build complete-case matrix
    matrix, _valid_indices = _build_item_matrix(answers_list, item_names)
    n_valid = len(_valid_indices)
    if n_valid <= n_items:
        return {
            "kmo_overall": None,
            "kmo_per_item": {},
            "bartlett_chi_square": None,
            "bartlett_df": None,
            "bartlett_p_value": None,
            "n_valid": n_valid,
            "interpretation": f"样本量不足：需要至少 {n_items + 1} 份完整回答，当前 {n_valid} 份",
            "error": "insufficient_data",
        }

    # Correlation matrix
    try:
        R = np.corrcoef(matrix, rowvar=False)  # shape (k, k)
    except Exception:
        return {
            "kmo_overall": None,
            "kmo_per_item": {},
            "bartlett_chi_square": None,
            "bartlett_df": None,
            "bartlett_p_value": None,
            "n_valid": n_valid,
            "interpretation": "相关矩阵计算失败（数据可能为常量）",
            "error": "computation_error",
        }

    # KMO: requires anti-image correlation matrix
    # anti-image = diag(R^-1)^(-1/2) * R^-1 * diag(R^-1)^(-1/2)
    try:
        R_inv = np.linalg.inv(R)
    except np.linalg.LinAlgError:
        return {
            "kmo_overall": 0.0,
            "kmo_per_item": {item_names[i]: 0.0 for i in range(n_items)},
            "bartlett_chi_square": None,
            "bartlett_df": None,
            "bartlett_p_value": None,
            "n_valid": n_valid,
            "interpretation": "相关矩阵不可逆（数据可能存在多重共线性）",
            "error": "singular_matrix",
        }

    diag_sqrt = np.sqrt(np.diag(R_inv))
    AIC = R_inv / np.outer(diag_sqrt, diag_sqrt)  # Anti-image correlation

    # KMO per item
    kmo_per_item: dict[str, float] = {}
    kmo_sum = 0.0
    for i in range(n_items):
        # Squared correlations (excluding diagonal)
        r2_sum = 0.0
        aic2_sum = 0.0
        for j in range(n_items):
            if i == j:
                continue
            r2_sum += R[i, j] ** 2
            aic2_sum += AIC[i, j] ** 2
        denom = r2_sum + aic2_sum
        kmo_i = r2_sum / denom if denom > 0 else 0.0
        kmo_per_item[item_names[i]] = round(float(kmo_i), 4)
        kmo_sum += kmo_i

    kmo_overall = kmo_sum / n_items if n_items > 0 else 0.0

    # Bartlett's test
    det_R = np.linalg.det(R)
    det_R = max(det_R, 1e-300)  # avoid log(0)
    k = n_items
    chi_sq = -(n_valid - 1 - (2 * k + 5) / 6) * math.log(det_R)
    df = k * (k - 1) / 2
    p_value = _chi_square_survival(chi_sq, df)

    # KMO interpretation
    if kmo_overall >= 0.9:
        kmo_label = "极佳（Marvelous）"
    elif kmo_overall >= 0.8:
        kmo_label = "良好（Meritorious）"
    elif kmo_overall >= 0.7:
        kmo_label = "一般（Middling）"
    elif kmo_overall >= 0.6:
        kmo_label = "勉强（Mediocre）"
    elif kmo_overall >= 0.5:
        kmo_label = "不足（Miserable）"
    else:
        kmo_label = "不适合因子分析（Unacceptable）"

    return {
        "kmo_overall": round(float(kmo_overall), 4),
        "kmo_per_item": kmo_per_item,
        "bartlett_chi_square": round(float(chi_sq), 4),
        "bartlett_df": int(df),
        "bartlett_p_value": round(float(p_value), 6),
        "n_valid": n_valid,
        "interpretation": kmo_label,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Multi-Construct Psychometrics
# ═══════════════════════════════════════════════════════════════════════════


def compute_construct_psychometrics(
    answers_list: list[dict],
    constructs: list[dict],
) -> dict:
    """Compute per-construct psychometrics and inter-construct correlations.

    Args:
        answers_list: List of answer dicts.
        constructs: List of {"name": str, "items": [str]} definitions.

    Returns:
        Dict with per-construct results and inter-construct correlation matrix.
    """
    construct_results = []
    construct_totals: dict[str, list[float]] = {}

    for c in constructs:
        items = c.get("items", [])
        name = c.get("name", "unnamed")
        n_items = len(items)

        if n_items < 2:
            construct_results.append({
                "name": name,
                "n_items": n_items,
                "n_valid": 0,
                "cronbach_alpha": None,
                "alpha_interpretation": "题项不足",
                "split_half": None,
                "item_total": [],
            })
            continue

        # Cronbach's alpha
        alpha_result = compute_cronbach_alpha(answers_list, items)
        alpha = alpha_result.get("alpha")

        # Split-half
        sh_result = compute_split_half_reliability(answers_list, items)
        sb = sh_result.get("spearman_brown")

        # Item-total
        it_result = compute_item_total_correlations(answers_list, items)

        # Compute total scores for inter-construct correlations
        scores = _compute_total_scores(answers_list, items)

        construct_totals[name] = scores

        construct_results.append({
            "name": name,
            "n_items": n_items,
            "n_valid": alpha_result.get("n_valid_responses", 0),
            "cronbach_alpha": alpha,
            "alpha_interpretation": _interpret_alpha(alpha) if alpha is not None else "N/A",
            "split_half": sb,
            "item_total": it_result.get("items", []),
        })

    # Inter-construct correlations
    inter_correlations = _compute_inter_construct_correlations(construct_totals)

    return {
        "constructs": construct_results,
        "inter_correlations": inter_correlations,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Internal Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _safe_float(val) -> float | None:
    """Convert a value to float, returning None for non-numeric values."""
    if val is None or val == "" or val == []:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _pearson_r(x: list[float], y: list[float]) -> float | None:
    """Compute Pearson correlation coefficient using pure Python."""
    n = len(x)
    if n < 2 or len(y) < 2:
        return None

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)

    if var_x < 1e-15 or var_y < 1e-15:
        return 0.0 if var_x < 1e-15 and var_y < 1e-15 else None

    r = cov / math.sqrt(var_x * var_y)
    return max(-1.0, min(1.0, r))


def _pearson_r_np(x: np.ndarray, y: np.ndarray) -> float | None:
    """Compute Pearson r using numpy."""
    mask = ~(np.isnan(x) | np.isnan(y))
    if mask.sum() < 2:
        return None
    try:
        r = np.corrcoef(x[mask], y[mask])[0, 1]
        if np.isnan(r):
            return None
        return float(max(-1.0, min(1.0, r)))
    except Exception:
        return None


def _build_item_matrix(
    answers_list: list[dict],
    item_names: list[str],
) -> tuple[np.ndarray, list[int]]:
    """Build a (n_cases × k_items) matrix of complete cases."""
    rows = []
    valid_indices = []
    for i, answers in enumerate(answers_list):
        vals = [_safe_float(answers.get(name)) for name in item_names]
        if None not in vals:
            rows.append(vals)
            valid_indices.append(i)
    if not rows:
        return np.zeros((0, len(item_names))), []
    return np.array(rows, dtype=float), valid_indices


def _compute_cronbach_alpha_from_matrix(
    matrix: np.ndarray,
    item_names: list[str],
) -> float | None:
    """Compute Cronbach's alpha from a numpy item matrix."""
    k = matrix.shape[1]
    if k < 2:
        return None

    complete_rows = ~np.any(np.isnan(matrix), axis=1)
    valid = matrix[complete_rows]
    n = valid.shape[0]
    if n < 2:
        return None

    item_vars = np.var(valid, axis=0, ddof=1)
    total = np.sum(valid, axis=1)
    total_var = np.var(total, ddof=1)

    if total_var < 1e-15:
        return 1.0

    alpha = (k / (k - 1)) * (1 - sum(item_vars) / total_var)
    return float(max(0.0, min(1.0, alpha)))


def _compute_total_scores(
    answers_list: list[dict],
    item_names: list[str],
) -> list[float]:
    """Compute total scores for a set of items (complete cases only)."""
    scores = []
    for answers in answers_list:
        vals = [_safe_float(answers.get(name)) for name in item_names]
        if None not in vals:
            scores.append(sum(v for v in vals if v is not None))
    return scores


def _compute_inter_construct_correlations(
    construct_totals: dict[str, list[float]],
) -> list[dict]:
    """Compute pairwise Pearson correlations between constructs."""
    names = list(construct_totals.keys())
    if len(names) < 2:
        return []

    correlations = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            scores_a = construct_totals[a]
            scores_b = construct_totals[b]
            # Align on complete cases (both constructs have values)
            min_len = min(len(scores_a), len(scores_b))
            if min_len < 3:
                correlations.append({
                    "construct_a": a,
                    "construct_b": b,
                    "correlation": None,
                })
                continue
            r = _pearson_r(scores_a[:min_len], scores_b[:min_len])
            correlations.append({
                "construct_a": a,
                "construct_b": b,
                "correlation": round(r, 4) if r is not None else None,
            })
    return correlations


def _chi_square_survival(chi_sq: float, df: float) -> float:
    """Approximate chi-square survival function (p-value).

    Uses scipy.stats.chi2.sf if available, otherwise falls back to a
    Wilson-Hilferty normal approximation.
    """
    try:
        from scipy.stats import chi2

        return float(chi2.sf(chi_sq, df))
    except ImportError:
        pass

    # Wilson-Hilferty approximation
    if chi_sq <= 0 or df <= 0:
        return 1.0

    z = ((chi_sq / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
    # Normal survival function approximation
    p = 0.5 * math.erfc(z / math.sqrt(2))
    return max(0.0, min(1.0, p))


# ═══════════════════════════════════════════════════════════════════════════
# Re-exported from analytics.py for convenience
# ═══════════════════════════════════════════════════════════════════════════


def compute_cronbach_alpha(
    answers_list: list[dict],
    item_names: list[str],
) -> dict:
    """Compute Cronbach's alpha (mirrors analytics.compute_cronbach_alpha).

    Kept here for self-contained psychometrics engine — avoids circular
    imports with the analytics module.
    """
    n_items = len(item_names)
    if n_items < 2:
        return {
            "alpha": None,
            "n_items": n_items,
            "n_valid_responses": 0,
            "item_variances": {},
            "total_variance": 0.0,
            "interpretation": "需要至少 2 个题项",
        }

    matrix, _valid = _build_item_matrix(answers_list, item_names)
    n_valid = matrix.shape[0]

    if n_valid < 2:
        return {
            "alpha": None,
            "n_items": n_items,
            "n_valid_responses": n_valid,
            "item_variances": {},
            "total_variance": 0.0,
            "interpretation": "有效回答数量不足",
        }

    item_vars = np.var(matrix, axis=0, ddof=1)
    total = np.sum(matrix, axis=1)
    total_var = np.var(total, ddof=1)

    if total_var < 1e-15:
        return {
            "alpha": 1.0,
            "n_items": n_items,
            "n_valid_responses": n_valid,
            "item_variances": {item_names[i]: round(float(item_vars[i]), 4) for i in range(n_items)},
            "total_variance": 0.0,
            "interpretation": "所有题项方差为零（常量回答）",
        }

    alpha = (n_items / (n_items - 1)) * (1 - sum(item_vars) / total_var)
    alpha = max(0.0, min(1.0, alpha))

    return {
        "alpha": round(float(alpha), 4),
        "n_items": n_items,
        "n_valid_responses": n_valid,
        "item_variances": {item_names[i]: round(float(item_vars[i]), 4) for i in range(n_items)},
        "total_variance": round(float(total_var), 4),
        "interpretation": _interpret_alpha(alpha),
    }


def _interpret_alpha(alpha: float | None) -> str:
    """Interpret Cronbach's alpha value."""
    if alpha is None:
        return "无法计算"
    if alpha >= 0.9:
        return "优秀（Excellent）"
    if alpha >= 0.8:
        return "良好（Good）"
    if alpha >= 0.7:
        return "可接受（Acceptable）"
    if alpha >= 0.6:
        return "存疑（Questionable）"
    return "较差（Poor）"
