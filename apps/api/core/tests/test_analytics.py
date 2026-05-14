"""Tests for analytics engine: frequencies, Cronbach's alpha, cross-tabs."""

from __future__ import annotations

import pytest
from app.core.analytics import (
    compute_cronbach_alpha,
    compute_cross_tab,
    compute_descriptive,
    compute_frequencies,
    compute_response_quality,
)


class TestComputeFrequencies:
    def test_simple_radiogroup(self):
        q_def = {
            "name": "q1",
            "type": "radiogroup",
            "choices": [
                {"value": "a", "text": "选项A"},
                {"value": "b", "text": "选项B"},
            ],
        }
        answers = [{"q1": "a"}, {"q1": "a"}, {"q1": "b"}]
        result = compute_frequencies(answers, q_def)
        assert len(result) == 2
        assert result[0]["value"] == "选项A"
        assert result[0]["count"] == 2
        assert result[0]["percentage"] == pytest.approx(66.7, abs=0.1)
        assert result[1]["value"] == "选项B"
        assert result[1]["count"] == 1

    def test_checkbox_multi_select(self):
        q_def = {
            "name": "q1",
            "type": "checkbox",
            "choices": [
                {"value": "x", "text": "X"},
                {"value": "y", "text": "Y"},
            ],
        }
        answers = [{"q1": ["x", "y"]}, {"q1": ["x"]}]
        result = compute_frequencies(answers, q_def)
        # x: 2, y: 1
        counts = {r["value"]: r["count"] for r in result}
        assert counts["X"] == 2
        assert counts["Y"] == 1


class TestComputeDescriptive:
    def test_rating_stats(self):
        q_def = {"name": "rating", "type": "rating"}
        answers = [{"rating": 1}, {"rating": 2}, {"rating": 3}, {"rating": 4}, {"rating": 5}]
        result = compute_descriptive(answers, q_def)
        assert result is not None
        assert result["mean"] == 3.0
        assert result["median"] == 3.0
        assert result["n"] == 5

    def test_missing_values(self):
        q_def = {"name": "r", "type": "rating"}
        answers = [{"r": 1}, {"r": None}, {}, {"r": 3}]
        result = compute_descriptive(answers, q_def)
        assert result is not None
        assert result["n"] == 2
        assert result["mean"] == 2.0


class TestCrossTab:
    def test_2x2_matrix(self):
        q1_def = {
            "name": "gender",
            "choices": [{"text": "男"}, {"text": "女"}],
        }
        q2_def = {
            "name": "agree",
            "choices": [{"text": "同意"}, {"text": "不同意"}],
        }
        answers = [
            {"gender": "男", "agree": "同意"},
            {"gender": "男", "agree": "不同意"},
            {"gender": "女", "agree": "同意"},
            {"gender": "女", "agree": "同意"},
        ]
        result = compute_cross_tab(answers, q1_def, q2_def)
        assert result["n"] == 4
        # Row 0 (男): [1 agree, 1 不同意]
        assert result["matrix"][0] == [1, 1]
        # Row 1 (女): [2 agree, 0 不同意]
        assert result["matrix"][1] == [2, 0]


class TestCronbachAlpha:
    def test_known_alpha_high_reliability(self):
        """Test with data that should yield high alpha (>0.85).

        Simulating 5 Likert items where respondents are consistent:
        R1: all 4s, R2: all 3s, R3: all 5s, R4: all 2s, R5: all 4s
        With some small variation.
        """
        items = ["q1", "q2", "q3", "q4", "q5"]
        answers = [
            {"q1": 4, "q2": 4, "q3": 5, "q4": 4, "q5": 4},
            {"q1": 3, "q2": 3, "q3": 3, "q4": 3, "q5": 3},
            {"q1": 5, "q2": 5, "q3": 4, "q4": 5, "q5": 5},
            {"q1": 2, "q2": 2, "q3": 2, "q4": 2, "q5": 2},
            {"q1": 4, "q2": 5, "q3": 4, "q4": 4, "q5": 4},
        ]
        result = compute_cronbach_alpha(answers, items)
        # With 5 respondents who vary their answers proportionally,
        # alpha should be quite high (>0.85)
        assert result["alpha"] > 0.85
        assert result["n_items"] == 5
        assert result["n_valid_responses"] == 5

    def test_known_alpha_low_reliability(self):
        """Test with data that should yield low alpha.

        Random-ish responses across items.
        """
        items = ["q1", "q2", "q3"]
        answers = [
            {"q1": 1, "q2": 5, "q3": 3},
            {"q1": 5, "q2": 1, "q3": 4},
            {"q1": 2, "q2": 4, "q3": 1},
            {"q1": 3, "q2": 3, "q3": 5},
            {"q1": 4, "q2": 2, "q3": 2},
        ]
        result = compute_cronbach_alpha(answers, items)
        # With inconsistent responding, alpha should be low
        assert result["alpha"] < 0.7
        assert result["n_valid_responses"] == 5

    def test_alpha_requires_complete_cases(self):
        """Incomplete responses should be excluded from Cronbach's alpha."""
        items = ["q1", "q2"]
        answers = [
            {"q1": 1, "q2": 2},
            {"q1": 3, "q2": 4},
            {"q1": 5},  # missing q2 — excluded
            {"q1": 2, "q2": 3},
            {},  # both missing — excluded
        ]
        result = compute_cronbach_alpha(answers, items)
        assert result["n_valid_responses"] == 3  # only complete cases

    def test_alpha_single_item(self):
        """Single item yields alpha = 0."""
        result = compute_cronbach_alpha(
            [{"q1": 1}, {"q1": 2}], ["q1"]
        )
        assert result["alpha"] == 0.0
        assert result["n_items"] == 1

    def test_alpha_clamped_range(self):
        """Alpha should always be in [0, 1] range."""
        items = ["q1", "q2"]
        answers = [{"q1": 1, "q2": 1}, {"q1": 2, "q2": 2}, {"q1": 3, "q2": 3}]
        result = compute_cronbach_alpha(answers, items)
        assert 0.0 <= result["alpha"] <= 1.0


class TestResponseQuality:
    def test_speeders_detection(self):
        questions = [{"name": "q1", "type": "rating", "rateType": "labels"}]
        responses = [
            {
                "answers": {"q1": 3},
                "metadata": {"completion_time_seconds": 10.0},
                "is_complete": True,
            },
            {
                "answers": {"q1": 4},
                "metadata": {"completion_time_seconds": 120.0},
                "is_complete": True,
            },
            {
                "answers": {"q1": 2},
                "metadata": {"completion_time_seconds": 90.0},
                "is_complete": True,
            },
            {
                "answers": {"q1": 5},
                "metadata": {"completion_time_seconds": 100.0},
                "is_complete": True,
            },
        ]
        result = compute_response_quality(responses, questions)
        # median = (90+100)/2 = 95, threshold = 95/3 ≈ 31.7
        # Only the 10-second response is a speeder
        assert result["speeder_count"] == 1
        assert result["total_responses"] == 4
        assert result["complete_responses"] == 4

    def test_empty_responses(self):
        result = compute_response_quality([], [])
        assert result["total_responses"] == 0
        assert result["completion_rate"] == 0.0

    def test_straightliner_detection(self):
        """Straightliners give the same answer to >=80% of Likert items."""
        questions = [
            {"name": "q1", "type": "rating", "rateType": "labels"},
            {"name": "q2", "type": "rating", "rateType": "labels"},
            {"name": "q3", "type": "rating", "rateType": "labels"},
            {"name": "q4", "type": "rating", "rateType": "labels"},
            {"name": "q5", "type": "rating", "rateType": "labels"},
        ]
        responses = [
            # Straightliner: same answer for all 5 (100%)
            {
                "answers": {"q1": 3, "q2": 3, "q3": 3, "q4": 3, "q5": 3},
                "metadata": {},
                "is_complete": True,
            },
            # Normal: varied answers
            {
                "answers": {"q1": 1, "q2": 3, "q3": 5, "q4": 2, "q5": 4},
                "metadata": {},
                "is_complete": True,
            },
        ]
        result = compute_response_quality(responses, questions)
        assert result["straightliner_count"] == 1


# ── T9 Extended Quality Tests ────────────────────────────────────────────


class TestMissingPatterns:
    """Tests for compute_missing_patterns()."""

    def test_missing_patterns_basic(self):
        """Basic missing pattern detection."""
        from app.core.analytics import compute_missing_patterns

        questions = [
            {"name": "q1", "title": "Q1", "type": "radiogroup"},
            {"name": "q2", "title": "Q2", "type": "radiogroup"},
            {"name": "q3", "title": "Q3", "type": "radiogroup"},
        ]
        answers = [
            {"q1": "a", "q2": "b", "q3": "c"},  # Complete
            {"q1": "a", "q2": None, "q3": "c"},  # Missing q2
            {"q1": None, "q2": None, "q3": "c"},  # Missing q1 & q2
            {"q1": "a", "q2": "b", "q3": None},  # Missing q3
        ]

        result = compute_missing_patterns(answers, questions)

        # Per-item missing
        assert result["per_item_missing"]["q1"]["count"] == 1
        assert result["per_item_missing"]["q2"]["count"] == 2
        assert result["per_item_missing"]["q3"]["count"] == 1

        # Co-missing pairs: need at least 2 co-missing to appear
        # q1 & q2 both missing in answers[2] (1 occurrence — below threshold)
        # q2 & q3: q2 missing in answers[1], q3 missing in answers[3]
        assert isinstance(result["co_missing_pairs"], list)
        # Per-respondent distribution
        assert sum(d["n_respondents"] for d in result["respondent_distribution"]) == 4

    def test_missing_patterns_empty(self):
        """Missing patterns with no responses."""
        from app.core.analytics import compute_missing_patterns

        result = compute_missing_patterns([], [{"name": "q1", "title": "Q1", "type": "radiogroup"}])
        assert result["per_item_missing"] == {}
        assert result["co_missing_pairs"] == []
        assert result["respondent_distribution"] == []


class TestInconsistencyDetection:
    """Tests for compute_inconsistency_scores()."""

    def test_inconsistency_detection(self):
        """Detects contradictions between forward and reverse items."""
        from app.core.analytics import compute_inconsistency_scores

        questions = [
            {"name": "f1", "title": "I feel satisfied", "type": "rating", "rateType": "labels"},
            {"name": "f2", "title": "Life is good", "type": "rating", "rateType": "labels"},
            {"name": "r1", "title": "I feel sad (Reverse)", "type": "rating", "rateType": "labels"},
        ]
        answers = [
            {"f1": 5, "f2": 5, "r1": 1},  # Consistent (high forward, low reverse)
            {"f1": 5, "f2": 4, "r1": 5},  # INCONSISTENT (high on both)
        ]

        result = compute_inconsistency_scores(answers, questions)
        assert result["inconsistent_respondents"] == 1
        assert result["inconsistency_rate"] == 0.5

    def test_inconsistency_no_reverse_items(self):
        """No inconsistency detection without reverse items."""
        from app.core.analytics import compute_inconsistency_scores

        questions = [
            {"name": "f1", "title": "Not reversed", "type": "rating", "rateType": "labels"},
        ]
        answers = [{"f1": 5}]

        result = compute_inconsistency_scores(answers, questions)
        assert result["inconsistent_respondents"] == 0
        assert result["inconsistency_rate"] == 0.0


class TestAttentionCheck:
    """Tests for compute_attention_check_performance()."""

    def test_attention_check_pass(self):
        """Attention check detection."""
        from app.core.analytics import compute_attention_check_performance

        questions = [
            {"name": "ac1", "title": "Attention check", "type": "radiogroup",
             "isAttentionCheck": True, "correctAnswer": "2"},
            {"name": "q1", "title": "Normal question", "type": "radiogroup"},
        ]
        answers = [
            {"ac1": "2", "q1": "a"},  # Pass
            {"ac1": "1", "q1": "b"},  # Fail
            {"ac1": "2", "q1": "c"},  # Pass
        ]

        result = compute_attention_check_performance(answers, questions)
        assert result["attention_items"] == ["ac1"]
        assert result["pass_count"] == 2
        assert result["fail_count"] == 1
        assert result["pass_rate"] == pytest.approx(66.7, abs=0.2)
        assert len(result["failed_respondents"]) == 1

    def test_attention_check_none_present(self):
        """No attention checks in survey."""
        from app.core.analytics import compute_attention_check_performance

        questions = [
            {"name": "q1", "title": "Normal", "type": "radiogroup"},
        ]
        answers = [{"q1": "a"}]

        result = compute_attention_check_performance(answers, questions)
        assert result["attention_items"] == []
        assert result["pass_rate"] == 0.0


class TestResponseTimeDistribution:
    """Tests for compute_response_time_distribution()."""

    def test_time_distribution(self):
        """Response time distribution with known values."""
        from app.core.analytics import compute_response_time_distribution

        responses = [
            {"metadata": {"completion_time_seconds": 10}},
            {"metadata": {"completion_time_seconds": 20}},
            {"metadata": {"completion_time_seconds": 30}},
            {"metadata": {"completion_time_seconds": 40}},
            {"metadata": {"completion_time_seconds": 50}},
            {"metadata": {"completion_time_seconds": 60}},
            {"metadata": {"completion_time_seconds": 70}},
            {"metadata": {"completion_time_seconds": 80}},
            {"metadata": {"completion_time_seconds": 90}},
            {"metadata": {"completion_time_seconds": 100}},
        ]

        result = compute_response_time_distribution(responses)
        q = result["quantiles"]
        assert "p5" in q and "p50" in q and "p95" in q
        # Quantile at position index for 10 elements
        assert 40 <= q["p50"] <= 60  # Rough median check
        assert result["fast_threshold"] > 0
        assert result["slow_threshold"] > 0

    def test_time_distribution_empty(self):
        """Empty distribution returns zeros."""
        from app.core.analytics import compute_response_time_distribution

        result = compute_response_time_distribution([])
        assert result["quantiles"] == {}
        assert result["fast_respondents"] == 0


class TestIntegratedQuality:
    """Integration test for extended compute_response_quality()."""

    def test_extended_quality_result(self):
        """Extended response quality includes T9 fields."""
        from app.core.analytics import compute_response_quality

        questions = [
            {"name": "q1", "title": "Q1 rev (Reverse)", "type": "rating", "rateType": "labels"},
            {"name": "q2", "title": "Q2", "type": "rating", "rateType": "labels"},
            {"name": "ac1", "title": "Attention", "type": "radiogroup",
             "isAttentionCheck": True, "correctAnswer": "OK"},
        ]
        responses = [
            {
                "answers": {"q1": 5, "q2": 5, "ac1": "OK"},
                "metadata": {"completion_time_seconds": 120},
                "is_complete": True,
            },
            {
                "answers": {"q1": 5, "q2": 4, "ac1": "WRONG"},
                "metadata": {"completion_time_seconds": 10},
                "is_complete": True,
            },
        ]

        result = compute_response_quality(responses, questions)

        # Core fields
        assert result["total_responses"] == 2
        assert result["complete_responses"] == 2

        # T9 extended fields
        assert "missing_patterns" in result
        assert "inconsistency_rate" in result
        assert "response_time_distribution" in result
        assert "attention_check_pass_rate" in result
