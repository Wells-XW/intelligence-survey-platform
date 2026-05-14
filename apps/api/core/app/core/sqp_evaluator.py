"""SQP (Survey Quality Predictor) v2.1 inspired quality evaluator.

Based on the SQP framework (Saris & Gallhofer, 2014) and SQRA
(Survey Quality Risk Assessment) methodology. Evaluates generated
surveys across quality dimensions before the researcher sends them out.

Key dimensions:
- Reliability (Cronbach's α estimation, item-total correlations)
- Validity (content validity, construct validity indicators)
- Bias risk (social desirability, acquiescence, leading questions)
- Method effects (scale length, response format, order effects)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SqpItemScore:
    """Quality scores for a single survey item."""
    item_id: str
    reliability_estimate: float = 0.0       # predicted α contribution
    validity_estimate: float = 0.0          # content validity estimate
    bias_risk: float = 0.0                  # 0=no risk, 1=high risk
    clarity_score: float = 0.0              # readability / ambiguity
    method_effect_risk: float = 0.0         # scale/format artefacts
    overall_quality: float = 0.0            # weighted composite
    flags: list[str] = field(default_factory=list)  # detected issues
    suggestions: list[str] = field(default_factory=list)


@dataclass
class SqpSurveyReport:
    """Aggregate quality report for an entire survey."""
    survey_id: str = ""
    total_items: int = 0
    items: list[SqpItemScore] = field(default_factory=list)
    overall_quality: float = 0.0
    estimated_cronbach_alpha: float = 0.0
    total_flags: int = 0
    recommendation: str = ""  # "ready", "needs-revision", "needs-redesign"
    summary: str = ""


# ═════════════════════════════════════════════════════════════════════════
# Heuristic detection rules (Rule-based — AI augmentation in Phase 2)
# ═════════════════════════════════════════════════════════════════════════

# Chinese leading-question patterns (common in Chinese survey design)
_LEADING_PATTERNS_ZH = [
    r"难道不",           # "难道不..." = rhetorical negation
    r"您是否同意.{0,5}显然",  # "您是否同意...显然" = leading
    r"众所周知",          # "众所周知" = assumes consensus
    r"毫无疑问",          # "毫无疑问" = leading
    r"您不认为",          # "您不认为..." = double negative
    r"大家都.{0,3}认为",  # "大家都认为" = bandwagon
]

_LEADING_PATTERNS_EN = [
    r"Don't you agree",
    r"Wouldn't you say",
    r"Surely you",
    r"Obviously",
    r"Everyone knows",
    r"It is clear that",
]

# Double-barreled question markers (English & Chinese)
_DOUBLE_BARREL_MARKERS_ZH = [
    r"和.{1,20}以及",
    r"与.{1,20}和",
    r"以及.{1,20}和",
]

_DOUBLE_BARREL_MARKERS_EN = [
    r"\band\b.{1,30}\band\b",
    r"\bor\b.{1,30}\bor\b",
]

# Chinese social desirability triggers
_SOCIAL_DESIRABILITY_ZH = [
    "道德", "素质", "文明", "孝顺", "爱国",
    "诚实", "正直", "遵纪守法", "勤奋",
]

# Acquiescence risk: all-positive or all-negative statements
_ACQUIESCENCE_INDICATORS = [
    "完全同意", "非常满意", "总是",
    "Strongly agree", "Very satisfied", "Always",
]


def evaluate_item_quality(
    item_id: str,
    question_text: str,
    choices: Optional[list[str]] = None,
    has_reverse_coded: bool = False,
) -> SqpItemScore:
    """Evaluate a single survey item using heuristic quality rules.

    This is the rule-based (non-AI) evaluation engine. Phase 2 adds
    AI-augmented evaluation that cross-references the SQP framework
    and domain-specific knowledge.

    Args:
        item_id: Question identifier (e.g., "q1").
        question_text: The full question text.
        choices: Response options (if applicable).
        has_reverse_coded: Whether a reverse-coded companion exists.

    Returns:
        ``SqpItemScore`` with quality metrics and detection flags.
    """
    score = SqpItemScore(item_id=item_id)
    flags: list[str] = []
    suggestions: list[str] = []

    # 1. Clarity: word count heuristic
    word_count = len(question_text)
    if word_count < 5:
        flags.append("too_short")
        suggestions.append("题项过短，可能缺少必要上下文")
        score.clarity_score = 0.4
    elif word_count > 120:
        flags.append("too_long")
        suggestions.append("题项过长，建议拆分或简化（目标≤80字符）")
        score.clarity_score = 0.5
    else:
        score.clarity_score = 0.8

    # 2. Leading question detection
    for pattern in _LEADING_PATTERNS_ZH + _LEADING_PATTERNS_EN:
        if re.search(pattern, question_text):
            flags.append("leading_question")
            suggestions.append("题项具有引导性措辞，建议改为中性表述")
            score.bias_risk = max(score.bias_risk, 0.8)
            break
    else:
        score.bias_risk = 0.2

    # 3. Double-barreled detection
    for pattern in _DOUBLE_BARREL_MARKERS_ZH + _DOUBLE_BARREL_MARKERS_EN:
        if re.search(pattern, question_text):
            flags.append("double_barreled")
            suggestions.append("题项可能包含双重问题（一次问了两件事），建议拆分")
            score.bias_risk = max(score.bias_risk, 0.7)
            break

    # 4. Social desirability bias
    sd_count = sum(
        1 for term in _SOCIAL_DESIRABILITY_ZH
        if term in question_text
    )
    if sd_count >= 2:
        flags.append("social_desirability")
        suggestions.append("题项可能引发社会期望偏差，考虑使用间接测量或随机响应技术")
        score.bias_risk = max(score.bias_risk, 0.6)

    # 5. Response scale check
    if choices:
        n_choices = len(choices)
        if n_choices < 3:
            flags.append("insufficient_choices")
            suggestions.append("选项过少（<3），无法捕捉足够方差")
            score.method_effect_risk = 0.6
        elif n_choices > 9:
            flags.append("too_many_choices")
            suggestions.append("选项过多（>9），受访者可能信息过载")
            score.method_effect_risk = 0.4
        else:
            score.method_effect_risk = 0.1

        # Check for all-positive responses (acquiescence risk)
        pos_count = sum(
            1 for ind in _ACQUIESCENCE_INDICATORS
            if ind in " ".join(choices)
        )
        if pos_count > len(choices) * 0.7 and not has_reverse_coded:
            flags.append("acquiescence_risk")
            suggestions.append("选项以正向为主且无反向题，建议增加反向计分题项")
            score.method_effect_risk = max(score.method_effect_risk, 0.5)

    # 6. Reliability estimate (heuristic)
    score.reliability_estimate = 0.7  # default moderate
    if word_count < 20:
        score.reliability_estimate = 0.5  # too short = low reliability
    elif word_count > 80:
        score.reliability_estimate = 0.6  # too long may confuse

    # 7. Validity estimate (heuristic)
    score.validity_estimate = 0.7
    if "double_barreled" in flags:
        score.validity_estimate -= 0.2
    if "leading_question" in flags:
        score.validity_estimate -= 0.15

    # 8. Overall composite score
    score.overall_quality = round(
        score.reliability_estimate * 0.4
        + score.validity_estimate * 0.3
        + (1.0 - score.bias_risk) * 0.2
        + score.clarity_score * 0.1,
        3,
    )

    score.flags = flags
    score.suggestions = suggestions
    return score


def evaluate_survey_quality(
    survey_data: dict,
    survey_id: str = "",
) -> SqpSurveyReport:
    """Evaluate all items in a generated survey and produce a quality report.

    Args:
        survey_data: The full survey JSON (matching the generation output schema).
        survey_id: Optional survey identifier.

    Returns:
        ``SqpSurveyReport`` with per-item scores and overall assessment.
    """
    report = SqpSurveyReport(survey_id=survey_id)

    sections = survey_data.get("survey", survey_data).get("sections", [])
    all_items: list[SqpItemScore] = []
    total_items = 0
    total_flags = 0

    for section in sections:
        for q in section.get("questions", []):
            total_items += 1
            item_score = evaluate_item_quality(
                item_id=q.get("id", f"q{total_items}"),
                question_text=q.get("title", ""),
                choices=q.get("choices"),
                has_reverse_coded=False,  # could be inferred from title
            )
            all_items.append(item_score)
            total_flags += len(item_score.flags)

    report.total_items = total_items
    report.items = all_items
    report.total_flags = total_flags

    # Aggregate quality
    if all_items:
        report.overall_quality = round(
            sum(i.overall_quality for i in all_items) / len(all_items), 3
        )
        report.estimated_cronbach_alpha = round(
            sum(i.reliability_estimate for i in all_items) / len(all_items), 3
        )

    # Recommendation
    flag_ratio = total_flags / max(total_items, 1)
    if report.overall_quality >= 0.75 and flag_ratio < 0.2:
        report.recommendation = "ready"
        report.summary = "问卷质量良好，可直接发布或进行小规模前测。"
    elif report.overall_quality >= 0.5:
        report.recommendation = "needs-revision"
        report.summary = f"问卷存在 {total_flags} 个质量风险点，建议逐项修订后再发布。"
    else:
        report.recommendation = "needs-redesign"
        report.summary = "问卷质量存在严重问题，建议重新设计核心题项。"

    return report


def format_sqp_report(report: SqpSurveyReport) -> str:
    """Format an SQP report as a human-readable Markdown string."""
    lines = [
        "# SQP 问卷质量评估报告",
        "",
        f"**总题项数**: {report.total_items}",
        f"**综合质量得分**: {report.overall_quality:.2f} / 1.00",
        f"**预估 Cronbach's α**: {report.estimated_cronbach_alpha:.2f}",
        f"**风险标志数**: {report.total_flags}",
        f"**建议**: {report.recommendation}",
        f"**总结**: {report.summary}",
        "",
        "## 各题项详细评分",
        "",
        "| 题号 | 质量分 | 信度 | 效度 | 偏差风险 | 风险标志 |",
        "|------|--------|------|------|----------|----------|",
    ]

    for item in report.items:
        flags_str = ", ".join(item.flags) if item.flags else "无"
        lines.append(
            f"| {item.item_id} | {item.overall_quality:.2f} | "
            f"{item.reliability_estimate:.2f} | {item.validity_estimate:.2f} | "
            f"{item.bias_risk:.2f} | {flags_str} |"
        )

    # Suggestions section
    items_with_suggestions = [i for i in report.items if i.suggestions]
    if items_with_suggestions:
        lines.append("")
        lines.append("## 改进建议")
        lines.append("")
        for item in items_with_suggestions:
            lines.append(f"### {item.item_id}")
            for s in item.suggestions:
                lines.append(f"- {s}")
            lines.append("")

    return "\n".join(lines)
