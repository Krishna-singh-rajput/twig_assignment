"""Configuration module for the B2B Market Intelligence Job Data Pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Load .env file from project root
load_dotenv()


@dataclass
class PipelineConfig:
    """Central configuration for pipeline execution."""

    # Project directories
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    data_dir: Path = field(init=False)
    output_dir: Path = field(init=False)
    cache_dir: Path = field(init=False)

    # Database & storage paths
    db_path: Path = field(init=False)
    duckdb_path: Path = field(init=False)
    csv_output_path: Path = field(init=False)
    json_output_path: Path = field(init=False)

    # Scraping politeness & rate limits
    request_delay_seconds: float = float(os.getenv("REQUEST_DELAY_SECONDS", "1.0"))
    request_timeout_seconds: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "15.0"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    user_agent: str = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 (B2B-Job-Pipeline/1.0)",
    )

    # ATS & Source Targets
    greenhouse_tokens: List[str] = field(
        default_factory=lambda: ["stripe", "airbnb", "databricks", "figma"]
    )
    # Palantir on Lever; note: Plaid migrated off Lever, so spotify is included as active Lever company
    lever_sites: List[str] = field(
        default_factory=lambda: ["palantir", "spotify"]
    )
    # Also support testing plaid gracefully
    lever_fallback_sites: List[str] = field(
        default_factory=lambda: ["plaid"]
    )
    hn_whoishiring_url: str = os.getenv(
        "HN_WHOISHIRING_URL", "https://news.ycombinator.com/submitted?id=whoishiring"
    )

    # LLM Settings
    # Supported: "rule" (default offline deterministic), "openai", "gemini", "ollama"
    llm_provider: str = os.getenv("LLM_PROVIDER", "rule").lower()
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # Pipeline limits
    max_postings_per_source: int = int(os.getenv("MAX_POSTINGS_PER_SOURCE", "150"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    def __post_init__(self) -> None:
        self.data_dir = self.project_root / "data"
        self.output_dir = self.project_root / "output"
        self.cache_dir = self.data_dir / "raw_cache"

        self.db_path = Path(os.getenv("DB_PATH", str(self.data_dir / "postings.db")))
        self.duckdb_path = Path(os.getenv("DUCKDB_PATH", str(self.data_dir / "postings.duckdb")))
        self.csv_output_path = Path(os.getenv("CSV_OUTPUT_PATH", str(self.output_dir / "job_postings.csv")))
        self.json_output_path = Path(os.getenv("JSON_OUTPUT_PATH", str(self.output_dir / "job_postings.json")))

        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


# Default singleton instance
config = PipelineConfig()
