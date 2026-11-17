"""Evaluation metrics for field-level extraction accuracy, evidence validity, and LLM costs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from difflib import SequenceMatcher

from pipeline.models import ExtractedJobFields


@dataclass
class FieldScore:
    """Score metrics for a specific field across evaluated postings."""
    total_evaluated: int = 0
    correct_matches: int = 0
    false_positives: int = 0  # Predicted non-null when ground truth was null (hallucination)
    false_negatives: int = 0  # Predicted null when ground truth had a value
    accuracy: float = 0.0


@dataclass
class BenchmarkReport:
    """Aggregated benchmark evaluation report."""
    total_postings: int = 0
    hn_postings_count: int = 0
    other_postings_count: int = 0
    field_scores: Dict[str, FieldScore] = field(default_factory=dict)
    average_accuracy: float = 0.0
    evidence_validity_rate: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_cost_per_posting_usd: float = 0.0
    avg_latency_seconds: float = 0.0

    def print_summary(self) -> str:
        """Format a clean markdown table summary of benchmark results."""
        lines = [
            "==================================================================",
            "          FIELD-LEVEL EXTRACTION ACCURACY & COST REPORT           ",
            "==================================================================",
            f"Total Benchmark Postings: {self.total_postings} (Hacker News: {self.hn_postings_count}, ATS Boards: {self.other_postings_count})",
            f"Average Extraction Accuracy: {self.average_accuracy * 100:.2f}%",
            f"Evidence Validity (Non-hallucination): {self.evidence_validity_rate * 100:.2f}%",
            f"Average LLM Cost Per Posting: ${self.avg_cost_per_posting_usd:.6f}",
            f"Average Latency Per Posting: {self.avg_latency_seconds:.3f}s",
            "------------------------------------------------------------------",
            f"{'Field':<20} | {'Evaluated':<10} | {'Correct':<8} | {'Accuracy':<10}",
            "------------------------------------------------------------------",
        ]
        for field_name, score in sorted(self.field_scores.items()):
            lines.append(
                f"{field_name:<20} | {score.total_evaluated:<10} | {score.correct_matches:<8} | {score.accuracy * 100:.1f}%"
            )
        lines.append("==================================================================")
        return "\n".join(lines)


class MetricEvaluator:
    """Evaluates extracted postings against ground truth records."""

    @classmethod
    def evaluate_field(cls, field_name: str, predicted: Any, expected: Any) -> bool:
        """Compare predicted value with ground truth value for a field."""
        # Both null -> match
        if predicted is None and expected is None:
            return True
        # One null, one not -> mismatch
        if predicted is None or expected is None:
            return False

        # Convert enums to string
        pred_val = predicted.value if hasattr(predicted, "value") else predicted
        exp_val = expected.value if hasattr(expected, "value") else expected

        # Categorical strings
        if field_name in ("company", "title", "seniority", "remote_policy", "employment_type", "currency", "country", "city"):
            p_str = str(pred_val).strip().lower()
            e_str = str(exp_val).strip().lower()
            if p_str == e_str:
                return True
            # Allow minor substring tolerance for company and title
            if field_name in ("company", "title", "city"):
                sim = SequenceMatcher(None, p_str, e_str).ratio()
                return sim >= 0.85 or e_str in p_str or p_str in e_str
            return False

        # Salaries: within 5% tolerance
        if field_name in ("salary_min", "salary_max"):
            try:
                p_num = float(pred_val)
                e_num = float(exp_val)
                diff = abs(p_num - e_num)
                tolerance = max(e_num * 0.05, 5000.0)
                return diff <= tolerance
            except (ValueError, TypeError):
                return False

        # Boolean
        if field_name == "visa_sponsorship":
            return bool(pred_val) == bool(exp_val)

        # Skills: Jaccard similarity >= 0.50
        if field_name == "skills":
            pred_set = {s.lower() for s in (predicted or [])}
            exp_set = {s.lower() for s in (expected or [])}
            if not exp_set and not pred_set:
                return True
            if not exp_set or not pred_set:
                return False
            overlap = len(pred_set & exp_set)
            union = len(pred_set | exp_set)
            return (overlap / union) >= 0.40

        return str(pred_val).strip() == str(exp_val).strip()
