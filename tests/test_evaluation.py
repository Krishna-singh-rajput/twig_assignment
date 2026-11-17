"""Unit tests for the 20-posting quality evaluation benchmark and metrics calculations."""

from pipeline.evaluation.benchmark import BenchmarkRunner
from pipeline.evaluation.metrics import MetricEvaluator


def test_metric_evaluator_comparisons():
    """Verify field-level comparison rules: tolerance, enums, null matching, skills overlap."""
    # Null matching
    assert MetricEvaluator.evaluate_field("salary_min", None, None) is True
    assert MetricEvaluator.evaluate_field("salary_min", 150000.0, None) is False
    assert MetricEvaluator.evaluate_field("salary_min", None, 150000.0) is False

    # Salary tolerance (within 5%)
    assert MetricEvaluator.evaluate_field("salary_min", 150000.0, 152000.0) is True
    assert MetricEvaluator.evaluate_field("salary_min", 150000.0, 200000.0) is False

    # Categorical string matching with minor tolerance
    assert MetricEvaluator.evaluate_field("company", "Stripe, Inc.", "Stripe") is True
    assert MetricEvaluator.evaluate_field("title", "Senior Data Engineer", "Senior Data Engineer, Platform") is True

    # Skills Jaccard overlap
    assert MetricEvaluator.evaluate_field("skills", ["Python", "Spark", "SQL"], ["Python", "Spark"]) is True
    assert MetricEvaluator.evaluate_field("skills", ["Java", "C++"], ["Python", "Spark"]) is False


def test_20_posting_benchmark_execution():
    """Verify running benchmark on the 20-posting hand-labeled dataset meets quality bars."""
    runner = BenchmarkRunner()
    report = runner.run_benchmark()

    # Required specification checks:
    # 1. Total postings == 20
    assert report.total_postings == 20
    # 2. At least 10 from Hacker News
    assert report.hn_postings_count >= 10, f"Expected >= 10 HN postings, got {report.hn_postings_count}"
    # 3. High field accuracy
    assert report.average_accuracy >= 0.85, f"Expected accuracy >= 85%, got {report.average_accuracy * 100:.1f}%"
    # 4. Evidence validity (no hallucinations)
    assert report.evidence_validity_rate >= 0.95
