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
