"""LLM Structured Extractor supporting OpenAI, Gemini, Ollama, and Rule fallback."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Optional

from pipeline.config import config
from pipeline.extractors.base import BaseExtractor, ExtractionResult
from pipeline.extractors.prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_PROMPT_TEMPLATE,
)
from pipeline.extractors.rule_extractor import RuleBasedExtractor
from pipeline.models import ExtractedJobFields, RawJobPosting

logger = logging.getLogger("pipeline.extractors.llm")


# Pricing per 1M tokens (USD)
PRICING_TABLE = {
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "gpt-3.5-turbo": {"prompt": 0.50, "completion": 1.50},
    "gemini-1.5-flash": {"prompt": 0.075, "completion": 0.30},
    "gemini-2.0-flash": {"prompt": 0.10, "completion": 0.40},
}


class LLMExtractor(BaseExtractor):
    """Structured LLM extractor with strict schema enforcement, evidence tracking,
    and automatic fallback to RuleBasedExtractor when offline or unconfigured.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self.provider = (provider or config.llm_provider).lower()
        self.model = model or config.llm_model
        self.api_key = api_key or (
            config.openai_api_key if self.provider == "openai" else config.gemini_api_key
        )
        self.rule_fallback = RuleBasedExtractor()

    def _prepare_prompt_text(self, posting: RawJobPosting) -> str:
        """Prune full text to relevant sections (first 1200 chars + salary sections)
        to prevent sending whole HTML pages or excessive boilerplate to the LLM.
        """
        full_text = posting.body_raw

        # If text is already concise (e.g. Hacker News comment), keep it
        if len(full_text) < 1500:
            return full_text

        # For long ATS postings: keep header/intro (1000 chars) + any section mentioning salary/compensation/benefits
        intro = full_text[:1000]
        comp_matches = re.finditer(
            r"(?:salary|compensation|pay\s+range|base\s+pay|\$|\/yr)[\s\S]{0,400}",
            full_text,
            re.IGNORECASE,
        )
        comp_sections = [m.group(0) for m in comp_matches]

        combined = f"{intro}\n\n[...]\n" + "\n---\n".join(comp_sections[:2])
        return combined[:2500]

    def extract(self, posting: RawJobPosting) -> ExtractionResult:
        """Extract structured fields using configured LLM provider or fallback."""
        if self.provider == "rule" or not self.api_key and self.provider in ("openai", "gemini"):
            # Use deterministic rule extractor
            return self.rule_fallback.extract(posting)

        start_time = time.time()
        pruned_text = self._prepare_prompt_text(posting)
        user_prompt = EXTRACTION_USER_PROMPT_TEMPLATE.format(
            company_hint=posting.company_raw,
            title_hint=posting.title_raw,
            location_hint=posting.location_raw or "Not specified",
            text=pruned_text,
        )

        try:
            if self.provider == "openai":
                return self._call_openai(user_prompt, start_time, posting)
            elif self.provider == "gemini":
                return self._call_gemini(user_prompt, start_time, posting)
            else:
                logger.warning(f"Unsupported provider '{self.provider}', falling back to rule extractor.")
                return self.rule_fallback.extract(posting)
        except Exception as exc:
            logger.warning(f"LLM call failed ({exc}), falling back to deterministic rule extractor.")
            fallback_res = self.rule_fallback.extract(posting)
            fallback_res.model_used = f"rule-fallback (error: {str(exc)[:50]})"
            return fallback_res

    def _call_openai(self, user_prompt: str, start_time: float, posting: RawJobPosting) -> ExtractionResult:
        """Call OpenAI chat completion."""
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=600,
        )

        content = response.choices[0].message.content or "{}"
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0

        # Cost calculation
        pricing = PRICING_TABLE.get(self.model, PRICING_TABLE["gpt-4o-mini"])
        cost = (prompt_tokens * pricing["prompt"] + completion_tokens * pricing["completion"]) / 1_000_000

        data = json.loads(content)
        fields = ExtractedJobFields.model_validate(data)

        return ExtractionResult(
            fields=fields,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            latency_seconds=time.time() - start_time,
            model_used=f"openai/{self.model}",
            raw_response=content,
        )

    def _call_gemini(self, user_prompt: str, start_time: float, posting: RawJobPosting) -> ExtractionResult:
        """Call Google Gemini API."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=self.model if "gemini" in self.model else "gemini-1.5-flash",
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=EXTRACTION_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )

        content = response.text or "{}"
        # Estimate tokens if not directly in metadata
        prompt_tokens = len(user_prompt) // 4
        completion_tokens = len(content) // 4
        cost = (prompt_tokens * 0.075 + completion_tokens * 0.30) / 1_000_000

        data = json.loads(content)
        fields = ExtractedJobFields.model_validate(data)

        return ExtractionResult(
            fields=fields,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            latency_seconds=time.time() - start_time,
            model_used=f"gemini/{self.model}",
            raw_response=content,
        )
