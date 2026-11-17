"""CLI interface for running the pipeline, evaluating quality benchmarks, and exporting data."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from pipeline.config import config
from pipeline.evaluation.benchmark import BenchmarkRunner
from pipeline.extractors.llm_extractor import LLMExtractor
from pipeline.orchestrator import PipelineOrchestrator
from pipeline.storage.database import DatabaseManager


def setup_logging(verbose: bool = False) -> None:
    """Configure structured logging output."""
    level = logging.DEBUG if verbose else getattr(logging, config.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cmd_run(args: argparse.Namespace) -> None:
    """Execute the pipeline."""
    setup_logging(args.verbose)
    logger = logging.getLogger("pipeline.cli")
    logger.info("Starting B2B Market Intelligence Job Pipeline run...")

    # Configure extractor
    extractor = LLMExtractor(
        provider=args.provider or config.llm_provider,
        model=args.model or config.llm_model,
        api_key=args.api_key,
    )

    db = DatabaseManager(args.db or config.db_path)
    orchestrator = PipelineOrchestrator(db_manager=db, extractor=extractor)

    sources = args.sources.split(",") if args.sources else None
    stats = orchestrator.run(
        sources=sources,
        max_postings_per_source=args.limit,
    )

    print("\n" + "=" * 60)
    print("           PIPELINE RUN EXECUTION SUMMARY")
    print("=" * 60)
    for k, v in stats.items():
        print(f"  {k:<25}: {v}")
    print("=" * 60)
    print(f"  SQLite Database : {db.db_path}")
    print(f"  CSV Export      : {config.csv_output_path}")
    print(f"  JSON Export     : {config.json_output_path}")
    print(f"  DuckDB Export   : {config.duckdb_path}")
    print("=" * 60 + "\n")


def cmd_evaluate(args: argparse.Namespace) -> None:
    """Evaluate pipeline extraction quality against the 20 hand-labeled postings."""
    setup_logging(args.verbose)
    logger = logging.getLogger("pipeline.cli")
    logger.info("Executing benchmark evaluation against 20 hand-labeled postings...")

    extractor = LLMExtractor(
        provider=args.provider or config.llm_provider,
        model=args.model or config.llm_model,
        api_key=args.api_key,
    )

    runner = BenchmarkRunner(extractor=extractor)
    report = runner.run_benchmark()
    print("\n" + report.print_summary() + "\n")


def cmd_stats(args: argparse.Namespace) -> None:
    """Display current database record statistics and recent change history."""
    setup_logging(args.verbose)
    db = DatabaseManager(args.db or config.db_path)
    postings = db.get_all_postings()
    history = db.history.get_history()

    print("\n" + "=" * 60)
    print("              DATABASE SUMMARY & AUDIT STATS")
    print("=" * 60)
    print(f"  Total Postings Stored : {len(postings)}")
    open_count = sum(1 for p in postings if p.status == "open")
    closed_count = sum(1 for p in postings if p.status == "closed")
    print(f"  Active Open Postings  : {open_count}")
    print(f"  Closed Postings       : {closed_count}")
    print(f"  Audit Changes Recorded: {len(history)}")
    print("------------------------------------------------------------")
    print("  Recent Change History Events (latest 10):")
    for h in history[:10]:
        print(f"    [{h['changed_at']}] Posting {h['posting_id'][:8]}... | {h['field_name']}: '{h['old_value']}' -> '{h['new_value']}'")
    print("=" * 60 + "\n")


def cmd_export(args: argparse.Namespace) -> None:
    """Export dataset to CSV, JSON, and DuckDB."""
    setup_logging(args.verbose)
    db = DatabaseManager(args.db or config.db_path)
    db.export_csv(config.csv_output_path)
    db.export_json(config.json_output_path)
    db.export_duckdb(config.duckdb_path)
    print(f"Exported data to {config.csv_output_path}, {config.json_output_path}, {config.duckdb_path}")


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m pipeline",
        description="B2B Market Intelligence Data & ML Job Ingestion Pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to execute")

    # 'run' command
    run_parser = subparsers.add_parser("run", help="Run the full scraping & extraction pipeline")
    run_parser.add_argument("--sources", type=str, default=None, help="Comma-separated list: greenhouse,lever,hackernews")
    run_parser.add_argument("--limit", type=int, default=None, help="Max postings per source (default from config)")
    run_parser.add_argument("--provider", type=str, default=None, choices=["rule", "openai", "gemini", "ollama"], help="Extraction provider")
    run_parser.add_argument("--model", type=str, default=None, help="Model name (e.g. gpt-4o-mini)")
    run_parser.add_argument("--api-key", type=str, default=None, help="API key for LLM provider")
    run_parser.add_argument("--db", type=str, default=None, help="Path to SQLite database")
    run_parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    # 'evaluate' command
    eval_parser = subparsers.add_parser("evaluate", help="Evaluate extraction accuracy against the 20 labeled benchmark postings")
    eval_parser.add_argument("--provider", type=str, default=None, choices=["rule", "openai", "gemini", "ollama"], help="Extraction provider")
    eval_parser.add_argument("--model", type=str, default=None, help="Model name")
    eval_parser.add_argument("--api-key", type=str, default=None, help="API key")
    eval_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    # 'stats' command
    stats_parser = subparsers.add_parser("stats", help="Show database counts and audit history")
    stats_parser.add_argument("--db", type=str, default=None, help="Path to SQLite database")
    stats_parser.add_argument("-v", "--verbose", action="store_true")

    # 'export' command
    export_parser = subparsers.add_parser("export", help="Export database to CSV, JSON, and DuckDB")
    export_parser.add_argument("--db", type=str, default=None, help="Path to SQLite database")
    export_parser.add_argument("-v", "--verbose", action="store_true")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        # Default to running the pipeline if no command is specified
        parser.print_help()
        return 0

    if args.command == "run":
        cmd_run(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "export":
        cmd_export(args)
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
