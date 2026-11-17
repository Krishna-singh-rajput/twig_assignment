"""Benchmark runner evaluating extraction accuracy, evidence grounding, and LLM cost."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from pipeline.config import config
from pipeline.evaluation.metrics import BenchmarkReport, FieldScore, MetricEvaluator
from pipeline.extractors.base import BaseExtractor
from pipeline.extractors.llm_extractor import LLMExtractor
from pipeline.models import RawJobPosting

logger = logging.getLogger("pipeline.evaluation.benchmark")


class BenchmarkRunner:
    """Executes evaluation across the 20 hand-labeled postings benchmark suite."""

    EVALUATED_FIELDS = [
        "company",
        "title",
        "seniority",
        "city",
        "country",
        "remote_policy",
        "salary_min",
        "salary_max",
        "currency",
        "employment_type",
        "skills",
        "visa_sponsorship",
    ]

    def __init__(
        self,
        labeled_dataset_path: Optional[Path] = None,
        extractor: Optional[BaseExtractor] = None,
    ) -> None:
        self.dataset_path = labeled_dataset_path or (config.project_root / "data" / "labeled_ground_truth.json")
        self.extractor = extractor or LLMExtractor()

    def run_benchmark(self) -> BenchmarkReport:
        """Run extraction on all labeled postings and calculate accuracy and telemetry."""
        logger.info(f"Loading benchmark dataset from {self.dataset_path}")
        with open(self.dataset_path, "r", encoding="utf-8") as f:
            items = json.load(f)

        total_postings = len(items)
        hn_count = sum(1 for it in items if it.get("source") == "hackernews")
        other_count = total_postings - hn_count

        field_scores: Dict[str, FieldScore] = {
            f: FieldScore() for f in self.EVALUATED_FIELDS
        }

        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost_usd = 0.0
        total_latency = 0.0
        evidence_checks_passed = 0
        total_evidence_checks = 0

        for it in items:
            raw_posting = RawJobPosting(
                source_name=it["source"],
                source_id=it["id"],
                source_url=it["source_url"],
                company_raw=it["company_raw"],
                title_raw=it["title_raw"],
                location_raw=it.get("location_raw"),
                body_raw=it["body_raw"],
            )

            extraction_res = self.extractor.extract(raw_posting)
            predicted = extraction_res.fields

            # Accumulate telemetry
            total_prompt_tokens += extraction_res.prompt_tokens
            total_completion_tokens += extraction_res.completion_tokens
            total_cost_usd += extraction_res.cost_usd
            total_latency += extraction_res.latency_seconds

            ground_truth = it["ground_truth"]

            # Evaluate each field
            for f_name in self.EVALUATED_FIELDS:
                score = field_scores[f_name]
                score.total_evaluated += 1

                pred_val = getattr(predicted, f_name, None)
                exp_val = ground_truth.get(f_name)

                is_correct = MetricEvaluator.evaluate_field(f_name, pred_val, exp_val)
                if is_correct:
                    score.correct_matches += 1
                else:
                    if pred_val is not None and exp_val is None:
                        score.false_positives += 1  # Hallucinated a value
                    elif pred_val is None and exp_val is not None:
                        score.false_negatives += 1  # Missed stated value

            # Verify evidence groundedness: check if evidence snippets exist in raw text
            for f_name, snippet in predicted.evidence.items():
                if snippet:
                    total_evidence_checks += 1
                    raw_full = f"{raw_posting.title_raw} {raw_posting.location_raw or ''} {raw_posting.body_raw}".lower()
                    if snippet.lower() in raw_full or any(word in raw_full for word in snippet.lower().split() if len(word) > 3):
                        evidence_checks_passed += 1

        # Calculate field accuracies
        overall_acc_sum = 0.0
        for score in field_scores.values():
            if score.total_evaluated > 0:
                score.accuracy = score.correct_matches / score.total_evaluated
                overall_acc_sum += score.accuracy

        avg_acc = overall_acc_sum / len(field_scores) if field_scores else 0.0
        evidence_rate = (
            evidence_checks_passed / total_evidence_checks if total_evidence_checks > 0 else 1.0
        )

        report = BenchmarkReport(
            total_postings=total_postings,
            hn_postings_count=hn_count,
            other_postings_count=other_count,
            field_scores=field_scores,
            average_accuracy=avg_acc,
            evidence_validity_rate=evidence_rate,
            total_prompt_tokens=total_prompt_tokens,
            total_completion_tokens=total_completion_tokens,
            total_cost_usd=total_cost_usd,
            avg_cost_per_posting_usd=total_cost_usd / total_postings if total_postings > 0 else 0.0,
            avg_latency_seconds=total_latency / total_postings if total_postings > 0 else 0.0,
        )

        return report
