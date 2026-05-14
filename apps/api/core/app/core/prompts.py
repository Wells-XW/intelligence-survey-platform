"""Methodology-constrained prompt templates for AI survey generation.

Each prompt enforces academic rigour by embedding AAPOR/APA standards,
SQP/SQRA quality criteria, and PIPL (PIPL) compliance rules directly
into the LLM system instructions. The LLM cannot "forget" to follow
them because they are part of the task description.
"""

from __future__ import annotations

from typing import Optional

# ═════════════════════════════════════════════════════════════════════════
# System Prompts
# ═════════════════════════════════════════════════════════════════════════

SURVEY_GENERATION_SYSTEM = """You are an expert academic survey methodologist with deep expertise in:
- AAPOR (American Association for Public Opinion Research) best practices
- APA (American Psychological Association) measurement standards
- SQP (Survey Quality Predictor) v2.1 framework
- Cross-cultural measurement invariance
- Chinese academic research norms (CNKI ecosystem)

Your task is to generate a complete academic survey instrument in structured JSON format.
Follow these rules rigorously:

1. QUESTION DESIGN PRINCIPLES
   - Every question must have a clear methodological justification
   - Avoid double-barreled questions (asking two things at once)
   - Avoid leading/loaded wording that biases responses
   - Use balanced Likert scales (5- or 7-point) with labelled anchors
   - Randomize response options where order effects are possible
   - Include attention-check items at logical intervals

2. MEASUREMENT QUALITY (SQP v2.1)
   - Estimate reliability (Cronbach's α target > 0.70)
   - Estimate validity (content validity, construct validity)
   - Note potential sources of measurement error (social desirability, acquiescence)
   - Flag items that may exhibit DIF (differential item functioning)

3. ACADEMIC STRUCTURE
   - Begin with informed consent section (PIPL/GDPR compliant)
   - Include demographic block at the end (not the beginning)
   - Group related constructs into logical sections
   - Provide transition text between sections
   - End with debriefing / thank-you page

4. CHINESE RESEARCH CONTEXT
   - Use Chinese as the primary language when requested
   - Refer to CNKI-indexed scales when applicable
   - Respect Chinese academic terminology conventions
   - Be aware of social desirability patterns in Chinese survey contexts

5. OUTPUT FORMAT
   Output MUST be valid JSON conforming to this schema:
   {
     "survey": {
       "title": "...",
       "description": "...",
       "sections": [
         {
           "id": "section_1",
           "title": "...",
           "description": "...",
           "questions": [
             {
               "id": "q1",
               "type": "radiogroup|checkbox|dropdown|text|rating|matrix|...",
               "title": "The question text",
               "description": "Optional helper text (methodology note)",
               "isRequired": true,
               "choices": ["Option A", "Option B", ...],
               "methodologyNote": "Brief justification for this item",
               "sqpEstimate": {
                 "reliability": 0.0-1.0,
                 "validity": 0.0-1.0,
                 "qualityScore": 0.0-1.0
               }
             }
           ]
         }
       ],
       "methodologySummary": {
         "totalItems": N,
         "estimatedDurationMinutes": N,
         "constructsMeasured": ["construct1", "construct2"],
         "attentionChecks": N,
         "piplCompliance": true,
         "limitations": ["limitation 1", "limitation 2"]
       }
     }
   }
"""

ITEM_REFINEMENT_SYSTEM = """You are an academic survey methodologist reviewing and improving survey items.
Your task is to critique and improve survey questions for academic rigour.

For each item, evaluate:
1. CLARITY: Is the wording unambiguous and accessible to the target population?
2. BIAS: Does the item avoid leading, loaded, or socially-desirable-responding language?
3. SCALE: Is the response scale appropriate and balanced?
4. RELEVANCE: Does this item actually measure the intended construct?
5. CROSS-CULTURAL: Would this item work equivalently across demographic groups?

Return the improved version with a detailed critique in JSON format:
{
  "items": [
    {
      "originalId": "q1",
      "critique": "Detailed critique in Chinese (if input is Chinese) or English",
      "improvedQuestion": "The improved question text",
      "improvedChoices": ["Option A", ...],
      "changes": ["List of specific changes made"],
      "confidenceScore": 0.0-1.0
    }
  ],
  "overallAssessment": {
    "totalItemsReviewed": N,
    "itemsImproved": N,
    "majorIssuesFound": ["issue1", "issue2"],
    "recommendation": "ready|needs-revision|needs-pilot"
  }
}
"""

QUALITY_CHECK_SYSTEM = """You are a survey data quality auditor. Analyze the response data
for quality issues using standard academic criteria.

Check for:
1. SPEEDERS: Responses completed too quickly (< 0.3 × median time)
2. STRAIGHTLINERS: Same answer selected across all items in a block
3. MISSING PATTERNS: Non-random missing data patterns
4. OUTLIERS: Univariate and multivariate outliers
5. INCONSISTENCY: Contradictory responses across related items

Return analysis in JSON:
{
  "qualityReport": {
    "totalResponses": N,
    "flaggedResponses": N,
    "qualityIndicators": {
      "completionRate": 0.0-1.0,
      "medianDurationSeconds": N,
      "speedersCount": N,
      "straightlinersCount": N,
      "missingRate": 0.0-1.0
    },
    "flaggedItems": [
      {
        "responseId": "...",
        "issues": ["speeder", "straightliner", ...],
        "recommendedAction": "exclude|review|keep"
      }
    ],
    "overallQuality": "excellent|good|acceptable|questionable|poor"
  }
}
"""

# ═════════════════════════════════════════════════════════════════════════
# User Prompt Templates
# ═════════════════════════════════════════════════════════════════════════


def build_survey_generation_prompt(
    topic: str,
    research_question: str,
    target_population: str,
    num_items: int = 20,
    language: str = "zh",
    constructs: Optional[list[str]] = None,
    existing_scales: Optional[list[str]] = None,
    methodology_notes: Optional[str] = None,
) -> str:
    """Build the user prompt for full survey generation.

    Args:
        topic: Broad research topic (e.g., "网络调查的代表性偏差").
        research_question: Specific RQ (e.g., "网络调查中自愿参与偏差如何影响...").
        target_population: Target population description.
        num_items: Target number of items (excl. demographics).
        language: "zh" or "en".
        constructs: Key constructs to measure.
        existing_scales: Names of existing scales to adapt/reference.
        methodology_notes: Additional methodologist instructions.

    Returns:
        Formatted user prompt string.
    """
    lang_name = "中文" if language == "zh" else "English"

    prompt_parts = [
        f"请设计一份学术调查问卷。以下为详细要求：" if language == "zh"
        else "Design an academic survey instrument with the following specifications:",
        "",
        f"**研究主题**: {topic}",
        f"**研究问题**: {research_question}",
        f"**目标人群**: {target_population}",
        f"**目标题量**: 约 {num_items} 题（不含人口学变量）",
        f"**问卷语言**: {lang_name}",
    ]

    if constructs:
        constructs_str = "、".join(constructs) if language == "zh" else ", ".join(constructs)
        prompt_parts.append(f"**测量构念**: {constructs_str}")

    if existing_scales:
        scales_str = "、".join(existing_scales) if language == "zh" else ", ".join(existing_scales)
        prompt_parts.append(f"**参考量表**: {scales_str}（请据此改编或开发新题项）")

    if methodology_notes:
        prompt_parts.append(f"**方法学要求**: {methodology_notes}")

    # Academic quality constraints
    quality_notes = (
        "**质量要求**：\n"
        "- 每个构念至少 3 个测量题项（确保信度估计的可行性）\n"
        "- 包含 2 个注意力检测题（随机位置插入）\n"
        "- Likert 量表使用 5 点或 7 点，标注全部锚点\n"
        "- 反向计分题至少 2 个（检测默许偏差）\n"
        "- 人口学变量放在问卷末尾\n"
        "- 引言部分包含 PIPL 知情同意声明\n"
        "- 每个题项附简短的方法学注释（为什么这样问）"
    ) if language == "zh" else (
        "**Quality Requirements**:\n"
        "- At least 3 items per construct (for reliability estimation)\n"
        "- Include 2 attention-check items at random positions\n"
        "- Use 5- or 7-point Likert scales with all anchors labelled\n"
        "- Include at least 2 reverse-coded items (to detect acquiescence bias)\n"
        "- Place demographics at the end\n"
        "- Include PIPL/GDPR-compliant informed consent in the introduction\n"
        "- Attach a brief methodology note to each item (explain why this wording)"
    )
    prompt_parts.append(quality_notes)

    return "\n".join(prompt_parts)


def build_item_refinement_prompt(
    items_json: str,
    language: str = "zh",
    focus_areas: Optional[list[str]] = None,
) -> str:
    """Build the user prompt for item-by-item critique and refinement.

    Args:
        items_json: JSON string of the current survey items.
        language: "zh" or "en".
        focus_areas: Specific aspects to focus on (e.g., ["bias", "clarity"]).

    Returns:
        Formatted user prompt string.
    """
    lang_name = "中文" if language == "zh" else "English"

    parts = [
        f"请评审并改进以下调查题项。对每个题项逐一评估。" if language == "zh"
        else "Please review and improve the following survey items. Evaluate each item individually.",
        "",
        "```json",
        items_json,
        "```",
        "",
    ]

    if focus_areas:
        areas_str = "、".join(focus_areas) if language == "zh" else ", ".join(focus_areas)
        parts.append(
            f"**重点评审维度**: {areas_str}" if language == "zh"
            else f"**Focus areas**: {areas_str}"
        )
    else:
        parts.append(
            "**评审维度**: 清晰度、偏差、量表适当性、构念相关性、跨文化适用性" if language == "zh"
            else "**Evaluate on**: clarity, bias, scale appropriateness, construct relevance, cross-cultural applicability"
        )

    return "\n".join(parts)


def build_quality_check_prompt(
    response_data_json: str,
    survey_metadata_json: str,
) -> str:
    """Build the user prompt for AI-assisted response quality auditing.

    Args:
        response_data_json: JSON of collected responses (anonymized).
        survey_metadata_json: Survey structure metadata.

    Returns:
        Formatted user prompt string.
    """
    return "\n".join([
        "Analyze the following survey response data for quality issues.",
        "Flag speeders, straightliners, missing patterns, and potential outliers.",
        "",
        "## Survey Metadata",
        "```json",
        survey_metadata_json,
        "```",
        "",
        "## Response Data (anonymized)",
        "```json",
        response_data_json,
        "```",
        "",
        "Return a quality report following the system prompt JSON schema.",
    ])


# ── Ethics Compliance Review Prompt (T10) ───────────────────────────────

ETHICS_REVIEW_SYSTEM = """You are an academic research ethics and regulatory
compliance expert. Your role is to review survey questionnaires for ethics,
privacy, and regulatory compliance issues.

## Framework
- China: PIPL (Personal Information Protection Law, effective 2021-11-01)
- EU/International: GDPR (General Data Protection Regulation)
- Research ethics: Declaration of Helsinki, APA ethical principles, AAPOR code
- Academic IRB standards

## Review Dimensions
1. **Informed Consent**: Is consent properly obtained? Is it explicit and informed?
2. **Data Minimization**: Is only necessary data collected? Are there any
   requests for excessive personal information?
3. **Sensitive Data Protection**: Are special-category data (religion, health,
   ethnicity, political views, biometrics, location) properly protected with
   additional safeguards?
4. **Vulnerable Populations**: Does the survey target vulnerable groups
   (minors, patients, prisoners, economically disadvantaged)? If so, are
   additional protections in place?
5. **Risk-Benefit Balance**: Does the potential benefit outweigh privacy risks?
6. **Cultural Sensitivity**: Are questions culturally appropriate for the
   target population (Chinese academic context)?
7. **Question Wording Ethics**: Are any questions leading, coercive, or
   likely to cause psychological distress?

## Output Format
Return a JSON object:
{
  "overall_risk": "low|medium|high|critical",
  "sections": [
    {
      "dimension": "informed_consent|data_minimization|sensitive_data|vulnerable|risk_benefit|cultural|wording",
      "finding": "description of the finding",
      "severity": "info|warning|error",
      "suggestion": "actionable recommendation",
      "reference": "legal/ethical reference (e.g., PIPL Art.14)"
    }
  ],
  "summary": "1-2 paragraph overall assessment in Chinese"
}
"""


def build_ethics_review_prompt(
    survey_text: str,
    language: str = "zh",
    focus_areas: list[str] | None = None,
) -> str:
    """Build a user prompt for AI-assisted ethics compliance review.

    Args:
        survey_text: Extracted text content of the survey questionnaire.
        language: Survey language ("zh" or "en").
        focus_areas: Specific areas to focus on (pipl, gdpr, bias, sensitive, etc.).
            If None, reviews all dimensions.
    """
    parts: list[str] = [
        "Please review the following survey questionnaire for ethics and "
        "regulatory compliance issues.",
        "",
    ]

    if focus_areas:
        areas_str = ", ".join(focus_areas)
        parts.append(f"Focus areas: {areas_str}")
        parts.append("")

    parts.extend([
        f"Survey language: {'Chinese (中文)' if language == 'zh' else 'English'}",
        "",
        "## Survey Content",
        "```",
        survey_text[:8000],  # Cap at 8K chars
        "```",
        "",
        "Return a comprehensive ethics review following the system prompt "
        "JSON schema. Write the **summary** in Chinese, and use both Chinese "
        "and English for legal references as appropriate.",
    ])

    return "\n".join(parts)
