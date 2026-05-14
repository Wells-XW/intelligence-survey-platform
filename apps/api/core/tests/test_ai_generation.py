"""Tests for AI survey generation engine."""

from __future__ import annotations

import json

import pytest

from app.core.ai_router import (
    ModelTarget,
    RouteDecision,
    TaskCategory,
    route_request,
)
from app.core.prompts import (
    build_item_refinement_prompt,
    build_quality_check_prompt,
    build_survey_generation_prompt,
)
from app.core.sqp_evaluator import (
    SqpItemScore,
    SqpSurveyReport,
    evaluate_item_quality,
    evaluate_survey_quality,
    format_sqp_report,
)
from app.schemas.ai_generation import (
    AiCostEstimate,
    SurveyGenerationRequest,
)


# ═════════════════════════════════════════════════════════════════════════
# AI Router Tests
# ═════════════════════════════════════════════════════════════════════════


class TestRouteRequest:
    """Multi-model routing logic."""

    def test_chinese_survey_generation_routes_to_deepseek(self):
        """Chinese survey generation should use DeepSeek (best cost/quality)."""
        decision = route_request(
            task=TaskCategory.SURVEY_GENERATION,
            has_chinese=True,
            has_sensitive_data=False,
        )
        assert decision.target == ModelTarget.DEEPSEEK
        assert "deepseek" in decision.model_name.lower()

    def test_sensitive_data_forces_local(self):
        """PIPL-sensitive data must route to local model (data sovereignty)."""
        decision = route_request(
            task=TaskCategory.SENSITIVE_PIPL,
            has_chinese=True,
            has_sensitive_data=True,
        )
        assert decision.target == ModelTarget.LOCAL_QWEN

    def test_quality_check_routes_to_gpt_mini(self):
        """Batch quality checks should use cheapest model."""
        decision = route_request(
            task=TaskCategory.QUALITY_CHECK,
            has_chinese=False,
            has_sensitive_data=False,
        )
        assert decision.target == ModelTarget.GPT_MINI

    def test_user_preference_overrides_routing(self):
        """User-specified model preference should override the routing table."""
        decision = route_request(
            task=TaskCategory.SURVEY_GENERATION,
            has_chinese=True,
            prefer_model=ModelTarget.CLAUDE,
        )
        assert decision.target == ModelTarget.CLAUDE

    def test_route_decision_has_reasoning(self):
        """Every route decision must include a human-readable reason."""
        decision = route_request(TaskCategory.SURVEY_GENERATION, has_chinese=True)
        assert decision.reasoning
        assert len(decision.reasoning) > 10


# ═════════════════════════════════════════════════════════════════════════
# SQP Evaluator Tests
# ═════════════════════════════════════════════════════════════════════════


class TestEvaluateItemQuality:
    """Single-item quality evaluation."""

    def test_well_constructed_item_scores_high(self):
        """A well-constructed item should score high on quality."""
        score = evaluate_item_quality(
            item_id="q1",
            question_text="您对目前的工作满意度如何？",
            choices=["非常不满意", "不满意", "一般", "满意", "非常满意"],
        )
        assert score.overall_quality > 0.5
        assert len(score.flags) == 0

    def test_leading_question_detected(self):
        """Questions with leading patterns should be flagged."""
        score = evaluate_item_quality(
            item_id="q1",
            question_text="难道您不认为当前的环保政策非常有效吗？",
        )
        assert "leading_question" in score.flags
        assert score.bias_risk > 0.5

    def test_double_barreled_detected(self):
        """Double-barreled questions (two things at once) should be flagged."""
        score = evaluate_item_quality(
            item_id="q1",
            question_text="您对公司的薪酬福利和职业发展机会以及工作环境满意吗？",
        )
        assert "double_barreled" in score.flags

    def test_too_short_item_flagged(self):
        """Very short items lack context."""
        score = evaluate_item_quality(item_id="q1", question_text="满意？")
        assert "too_short" in score.flags
        assert score.clarity_score < 0.5

    def test_normal_item_no_flags(self):
        """Normal items should not trigger false positives."""
        score = evaluate_item_quality(
            item_id="q1",
            question_text="请问您每天平均使用互联网多长时间？",
            choices=["少于1小时", "1-3小时", "3-5小时", "5-8小时", "8小时以上"],
        )
        # Only leading/bias checks — should be clean
        assert "leading_question" not in score.flags
        assert "double_barreled" not in score.flags


class TestEvaluateSurveyQuality:
    """Full survey quality evaluation."""

    def test_clean_survey_scores_high(self):
        """A well-structured survey should score well."""
        survey_data = {
            "survey": {
                "title": "居民幸福感调查",
                "sections": [
                    {
                        "id": "s1",
                        "title": "生活满意度",
                        "questions": [
                            {
                                "id": "q1",
                                "title": "您对目前的生活满意吗？",
                                "type": "radiogroup",
                                "choices": ["非常不满意", "不满意", "一般", "满意", "非常满意"],
                            },
                            {
                                "id": "q2",
                                "title": "您对未来生活有信心吗？",
                                "type": "radiogroup",
                                "choices": ["非常没有", "没有", "一般", "有", "非常有"],
                            },
                            {
                                "id": "q3",
                                "title": "总体而言，您觉得自己幸福吗？",
                                "type": "radiogroup",
                                "choices": ["非常不幸福", "不幸福", "一般", "幸福", "非常幸福"],
                            },
                        ],
                    }
                ],
            }
        }
        report = evaluate_survey_quality(survey_data)
        assert report.total_items == 3
        assert report.overall_quality > 0.6
        assert report.recommendation in ("ready", "needs-revision")

    def test_problematic_survey_scores_low(self):
        """A survey with leading/double-barreled items should score low."""
        survey_data = {
            "survey": {
                "title": "调查",
                "sections": [
                    {
                        "id": "s1",
                        "questions": [
                            {
                                "id": "q1",
                                "title": "难道您不认为社会道德在下降吗？",
                                "type": "radiogroup",
                            },
                            {
                                "id": "q2",
                                "title": "您对教育质量和医疗水平以及治安状况满意吗？",
                                "type": "radiogroup",
                            },
                        ],
                    }
                ],
            }
        }
        report = evaluate_survey_quality(survey_data)
        assert report.total_flags >= 2  # leading + double-barreled

    def test_format_sqp_report_returns_markdown(self):
        """SQP report formatting should produce valid Markdown."""
        survey_data = {
            "survey": {
                "sections": [
                    {
                        "id": "s1",
                        "questions": [
                            {"id": "q1", "title": "测试问题？", "type": "text"}
                        ],
                    }
                ],
            }
        }
        report = evaluate_survey_quality(survey_data)
        md = format_sqp_report(report)
        assert "# SQP" in md
        assert "q1" in md
        assert "质量得分" in md


# ═════════════════════════════════════════════════════════════════════════
# Prompt Template Tests
# ═════════════════════════════════════════════════════════════════════════


class TestPromptTemplates:
    """Methodology-constrained prompt construction."""

    def test_survey_generation_prompt_includes_all_fields(self):
        prompt = build_survey_generation_prompt(
            topic="网络调查代表性",
            research_question="自愿参与偏差如何影响估计精度？",
            target_population="18-60岁城镇居民",
            num_items=20,
            language="zh",
            constructs=["社会信任", "政治效能感"],
        )
        assert "网络调查代表性" in prompt
        assert "自愿参与偏差" in prompt
        assert "城镇居民" in prompt
        assert "社会信任" in prompt
        assert "PIPL" in prompt  # compliance should be embedded

    def test_item_refinement_prompt_includes_items(self):
        items_json = json.dumps({"questions": [{"id": "q1", "title": "test"}]})
        prompt = build_item_refinement_prompt(items_json, language="zh")
        assert "q1" in prompt
        assert "test" in prompt

    def test_quality_check_prompt_includes_data(self):
        prompt = build_quality_check_prompt(
            response_data_json='[{"id": "r1"}]',
            survey_metadata_json='{"title": "test"}',
        )
        assert "r1" in prompt
        assert "test" in prompt


# ═════════════════════════════════════════════════════════════════════════
# Schema & Cost Estimation Tests
# ═════════════════════════════════════════════════════════════════════════


class TestCostEstimation:
    """Pre-flight cost estimates."""

    def test_cost_estimate_is_low_for_typical_survey(self):
        """A 20-item Chinese survey should cost < ¥0.10 with DeepSeek."""
        from app.services.ai_generation import estimate_cost

        request = SurveyGenerationRequest(
            topic="测试研究主题",  # ≥3 chars
            research_question="测试问题" * 10,
            target_population="测试人群",
            num_items=20,
            language="zh",
        )
        cost = estimate_cost(request)
        assert cost.estimated_cost_cents < 1.0  # < 1 cent
        assert cost.estimated_cost_rmb < 0.10  # < ¥0.10
        assert cost.is_low_cost is True
        assert cost.model == "deepseek-chat"


class TestSchemas:
    """Pydantic schema validation."""

    def test_survey_generation_request_validation(self):
        """Valid request should pass validation."""
        req = SurveyGenerationRequest(
            topic="测试研究主题",
            research_question="这是一个测试研究问题，需要至少十个字",
            target_population="成年人",
        )
        assert req.num_items == 20  # default
        assert req.language == "zh"  # default

    def test_survey_generation_request_rejects_short_rq(self):
        """Research question too short should fail validation."""
        with pytest.raises(Exception):
            SurveyGenerationRequest(
                topic="测试",
                research_question="短",  # < 10 chars
                target_population="成年人",
            )

    def test_language_must_be_zh_or_en(self):
        """Only zh and en are valid languages."""
        with pytest.raises(Exception):
            SurveyGenerationRequest(
                topic="test",
                research_question="test question long enough",
                target_population="adults",
                language="fr",  # invalid
            )
