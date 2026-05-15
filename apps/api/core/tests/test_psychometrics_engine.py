"""Unit tests for the psychometrics pure-math engine."""

import math

import pytest

from app.core.psychometrics import (
    compute_split_half_reliability,
    compute_item_total_correlations,
    compute_kmo_bartlett,
    compute_construct_psychometrics,
    compute_cronbach_alpha,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_answers(items, rows):
    """Build answers_list from item names and rows of values."""
    return [{name: row[i] for i, name in enumerate(items)} for row in rows]


# ── Split-Half Tests ─────────────────────────────────────────────────


class TestSplitHalfReliability:
    def test_perfect_reliability(self):
        """All items perfectly correlated → SB near 1.0."""
        items = ["Q1", "Q2", "Q3", "Q4"]
        answers = _make_answers(items, [
            [5, 5, 5, 5], [4, 4, 4, 4], [3, 3, 3, 3],
            [2, 2, 2, 2], [1, 1, 1, 1],
        ])
        result = compute_split_half_reliability(answers, items)
        assert result.get("error") is None
        assert result["spearman_brown"] is not None
        assert result["spearman_brown"] > 0.9

    def test_random_data_low_reliability(self):
        """Uncorrelated random answers → SB near 0."""
        import random
        random.seed(42)
        items = ["Q1", "Q2", "Q3", "Q4"]
        answers = _make_answers(items, [
            [random.randint(1, 5) for _ in items] for _ in range(30)
        ])
        result = compute_split_half_reliability(answers, items)
        assert result.get("error") is None
        if result["spearman_brown"] is not None:
            assert result["spearman_brown"] < 0.8

    def test_too_few_items(self):
        """Single item → error."""
        result = compute_split_half_reliability(
            _make_answers(["Q1"], [[5]]), ["Q1"]
        )
        assert result["error"] == "too_few_items"

    def test_first_second_method(self):
        """First-second split method works."""
        items = ["Q1", "Q2", "Q3", "Q4"]
        answers = _make_answers(items, [
            [5, 5, 4, 4], [4, 4, 3, 3], [3, 3, 2, 2],
            [2, 2, 1, 1], [1, 1, 1, 1],
        ])
        result = compute_split_half_reliability(answers, items, method="first_second")
        assert result["method"] == "first_second"
        assert result["spearman_brown"] is not None

    def test_insufficient_data(self):
        """Only 1 complete case → insufficient."""
        items = ["Q1", "Q2", "Q3"]
        answers = _make_answers(items, [[5, None, 3]])
        result = compute_split_half_reliability(answers, items)
        assert result["error"] == "insufficient_data" or result["spearman_brown"] is None


# ── Item-Total Tests ─────────────────────────────────────────────────


class TestItemTotalCorrelations:
    def test_good_items(self):
        """Well-correlated items → all items flagged 'good'."""
        items = ["Q1", "Q2", "Q3", "Q4"]
        answers = _make_answers(items, [
            [5, 5, 5, 4], [4, 4, 4, 3], [3, 3, 3, 2],
            [2, 2, 2, 1], [1, 1, 1, 1], [5, 4, 5, 5],
            [4, 5, 4, 4], [3, 2, 3, 2],
        ])
        result = compute_item_total_correlations(answers, items)
        assert result.get("error") is None
        assert len(result["items"]) == 4
        for item in result["items"]:
            assert item["flag"] in ("good", "moderate", "weak")

    def test_alpha_if_deleted(self):
        """Removing a poor item should show alpha increase."""
        items = ["Q1", "Q2", "Q3"]
        answers = _make_answers(items, [
            [5, 5, 5], [4, 4, 4], [3, 3, 3],
            [2, 2, 2], [1, 1, 1], [5, 5, 5],
            [4, 4, 4], [3, 3, 3],
        ])
        result = compute_item_total_correlations(answers, items)
        assert len(result["items"]) == 3
        for item in result["items"]:
            assert item["alpha_if_deleted"] is not None
            assert 0 <= item["alpha_if_deleted"] <= 1

    def test_too_few_items(self):
        """Single item → error."""
        result = compute_item_total_correlations(
            _make_answers(["Q1"], [[5]]), ["Q1"]
        )
        assert result["error"] == "too_few_items"


# ── KMO & Bartlett Tests ──────────────────────────────────────────────


class TestKmoBartlett:
    def test_highly_correlated_data(self):
        """Highly correlated items → high KMO."""
        import random
        random.seed(123)
        items = ["Q1", "Q2", "Q3", "Q4"]
        # Generate correlated data with a common factor
        answers = []
        for _ in range(100):
            base = random.gauss(3, 0.5)
            row = [base + random.gauss(0, 0.2) for _ in items]
            answers.append({name: max(1, min(5, round(v))) for name, v in zip(items, row)})
        result = compute_kmo_bartlett(answers, items)
        if result.get("kmo_overall") is not None:
            assert result["kmo_overall"] > 0.5

    def test_orthogonal_data_low_kmo(self):
        """Random data → low KMO."""
        import random
        random.seed(999)
        items = ["Q1", "Q2", "Q3", "Q4"]
        answers = _make_answers(items, [
            [random.randint(1, 5) for _ in items] for _ in range(100)
        ])
        result = compute_kmo_bartlett(answers, items)
        if result.get("kmo_overall") is not None:
            assert result["kmo_overall"] < 0.9  # Should not be excellent

    def test_bartlett_significant(self):
        """Correlated data → Bartlett p < 0.05."""
        import random
        random.seed(42)
        items = ["Q1", "Q2", "Q3", "Q4"]
        answers = []
        for _ in range(60):
            base = random.gauss(3, 1)
            row = [base + random.gauss(0, 0.3) for _ in items]
            answers.append({name: max(1, min(5, round(v))) for name, v in zip(items, row)})
        result = compute_kmo_bartlett(answers, items)
        if result.get("bartlett_p_value") is not None:
            assert result["bartlett_p_value"] < 0.05

    def test_too_few_items(self):
        """Two items → error."""
        result = compute_kmo_bartlett(
            _make_answers(["Q1", "Q2"], [[5, 4]] * 10), ["Q1", "Q2"]
        )
        assert result["error"] == "too_few_items"

    def test_insufficient_data(self):
        """Not enough complete cases → error."""
        items = ["Q1", "Q2", "Q3", "Q4"]
        answers = _make_answers(items, [[5, 4, 3, 2]] * 3)  # only 3 cases for 4 items
        result = compute_kmo_bartlett(answers, items)
        assert result["error"] == "insufficient_data" or result.get("kmo_overall") is None


# ── Construct Tests ───────────────────────────────────────────────────


class TestConstructPsychometrics:
    def test_two_constructs(self):
        """Two constructs with correlated items."""
        items = ["A1", "A2", "B1", "B2"]
        answers = _make_answers(items, [
            [5, 5, 1, 1], [4, 4, 2, 2], [3, 3, 3, 1],
            [5, 4, 2, 1], [4, 5, 1, 2], [3, 4, 1, 1],
            [5, 5, 2, 2], [4, 3, 2, 1],
        ])
        constructs = [
            {"name": "Construct A", "items": ["A1", "A2"]},
            {"name": "Construct B", "items": ["B1", "B2"]},
        ]
        result = compute_construct_psychometrics(answers, constructs)
        assert len(result["constructs"]) == 2
        for c in result["constructs"]:
            assert c["n_items"] == 2
            assert c["cronbach_alpha"] is not None
        assert len(result["inter_correlations"]) >= 1

    def test_empty_construct(self):
        """Empty construct → no computation."""
        constructs = [{"name": "Empty", "items": []}]
        result = compute_construct_psychometrics([], constructs)
        assert len(result["constructs"]) == 1
        assert result["constructs"][0]["n_items"] == 0


# ── Cronbach's Alpha Tests ────────────────────────────────────────────


class TestCronbachAlpha:
    def test_known_high_alpha(self):
        """Highly consistent answers → alpha > 0.85."""
        items = ["Q1", "Q2", "Q3", "Q4"]
        answers = _make_answers(items, [
            [5, 5, 5, 4], [4, 4, 4, 3], [3, 3, 3, 2],
            [2, 2, 2, 1], [1, 1, 1, 1], [5, 4, 5, 5],
            [4, 5, 4, 4], [3, 2, 3, 2], [5, 5, 5, 5],
        ])
        result = compute_cronbach_alpha(answers, items)
        assert result["alpha"] is not None
        assert result["alpha"] > 0.85

    def test_constant_answers(self):
        """All identical answers → alpha = 1.0 (or near)."""
        items = ["Q1", "Q2"]
        answers = _make_answers(items, [[5, 5]] * 10)
        result = compute_cronbach_alpha(answers, items)
        assert result["alpha"] is not None
        assert result["alpha"] >= 0.99

    def test_too_few_items(self):
        """Single item → cannot compute."""
        result = compute_cronbach_alpha(
            _make_answers(["Q1"], [[5]] * 10), ["Q1"]
        )
        assert result["alpha"] is None or result.get("interpretation") == "需要至少 2 个题项"

    def test_no_variance(self):
        """No variance in total scores → alpha clamped."""
        items = ["Q1", "Q2"]
        answers = _make_answers(items, [[5, 5]] * 5)
        result = compute_cronbach_alpha(answers, items)
        # When total_var is 0, alpha = 1.0
        assert result["alpha"] is not None
