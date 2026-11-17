"""Base interface for all structured job field extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from pipeline.models import ExtractedJobFields, RawJobPosting


@dataclass
class ExtractionResult:
    """Encapsulates extracted fields alongside LLM token and cost telemetry."""
    fields: ExtractedJobFields
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_seconds: float = 0.0
    model_used: str = "rule"
    raw_response: Optional[str] = None


class BaseExtractor(ABC):
    """Abstract interface for extracting structured fields from a raw posting."""

    @abstractmethod
    def extract(self, posting: RawJobPosting) -> ExtractionResult:
        """Extract structured fields with source evidence from a raw posting."""
        pass
