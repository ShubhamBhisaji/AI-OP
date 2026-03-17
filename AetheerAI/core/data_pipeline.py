"""
AetheerAI/core/data_pipeline.py
================================
Three-stage data pipeline:  Ingest → Process → Export

Usage (CLI):
    python -m AetheerAI.core.data_pipeline                          # process default dataset
    python -m AetheerAI.core.data_pipeline --input data/raw/agent_runs.csv
    python -m AetheerAI.core.data_pipeline --input data/raw/agent_runs.csv --format jsonl

Importable API:
    from core.data_pipeline import DataPipeline
    result = DataPipeline().run("data/raw/agent_runs.csv")
    print(result.summary)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Resolve project root so relative paths always work ───────────────────────
_HERE = Path(__file__).resolve().parent          # AetheerAI/core/
_AETHEER_ROOT = _HERE.parent                     # AetheerAI/
_PROJECT_ROOT = _AETHEER_ROOT.parent             # project root

_DEFAULT_RAW_DIR      = _PROJECT_ROOT / "data" / "raw"
_DEFAULT_PROCESSED_DIR = _PROJECT_ROOT / "data" / "processed"
_DEFAULT_EXPORTS_DIR   = _PROJECT_ROOT / "data" / "exports"

_DEFAULT_INPUT = _DEFAULT_RAW_DIR / "agent_runs.csv"


# ─────────────────────────────────────────────────────────────────────────────
# Data containers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """Holds every artefact produced by a pipeline run."""
    raw_rows: int = 0
    clean_rows: int = 0
    dropped_rows: int = 0
    output_path: Path | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Ingest
# ─────────────────────────────────────────────────────────────────────────────

class IngestStage:
    """Read a CSV (file path or raw text) into a list of dicts."""

    REQUIRED_COLUMNS = {"run_id", "timestamp", "agent", "provider", "model",
                        "task_type", "tokens_in", "tokens_out", "latency_ms",
                        "success", "cost_usd"}

    def run(self, source: str | Path) -> tuple[list[dict], list[str]]:
        """
        Returns (rows, errors).  rows is empty on fatal errors.
        """
        errors: list[str] = []
        source = Path(source)

        if not source.exists():
            errors.append(f"Input file not found: {source}")
            return [], errors

        try:
            text = source.read_text(encoding="utf-8-sig")
        except OSError as exc:
            errors.append(f"Cannot read {source}: {exc}")
            return [], errors

        try:
            reader = list(csv.DictReader(io.StringIO(text)))
        except Exception as exc:
            errors.append(f"CSV parse error: {exc}")
            return [], errors

        if not reader:
            errors.append("CSV has no data rows.")
            return [], errors

        missing = self.REQUIRED_COLUMNS - set(reader[0].keys())
        if missing:
            errors.append(f"Missing expected columns: {sorted(missing)}")
            return [], errors

        logger.info("Ingest: loaded %d rows from %s", len(reader), source)
        return reader, errors


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Process (clean + enrich + aggregate)
# ─────────────────────────────────────────────────────────────────────────────

class ProcessStage:
    """
    Clean, validate, type-cast, and enrich each row.
    Produces:
      - cleaned row list (bad rows dropped with reason logged)
      - per-agent summary stats
      - per-provider summary stats
      - per-task_type summary stats
    """

    def run(
        self, rows: list[dict]
    ) -> tuple[list[dict], dict[str, Any], list[str]]:
        """
        Returns (clean_rows, aggregates, drop_reasons).
        """
        clean: list[dict] = []
        drop_reasons: list[str] = []

        for raw in rows:
            row, reason = self._clean_row(raw)
            if reason:
                drop_reasons.append(reason)
            else:
                clean.append(row)

        aggregates = self._aggregate(clean)
        logger.info(
            "Process: %d clean rows, %d dropped", len(clean), len(drop_reasons)
        )
        return clean, aggregates, drop_reasons

    # ── Per-row cleaning ──────────────────────────────────────────────────────

    def _clean_row(self, raw: dict) -> tuple[dict | None, str]:
        run_id = raw.get("run_id", "").strip()
        if not run_id:
            return None, "blank run_id"

        # Validate ISO timestamp
        ts_raw = raw.get("timestamp", "").strip()
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except ValueError:
            return None, f"{run_id}: invalid timestamp '{ts_raw}'"

        # Cast numeric fields
        try:
            tokens_in  = int(raw.get("tokens_in",  0))
            tokens_out = int(raw.get("tokens_out", 0))
            latency_ms = int(raw.get("latency_ms", 0))
            cost_usd   = float(raw.get("cost_usd", 0.0))
        except (ValueError, TypeError) as exc:
            return None, f"{run_id}: numeric cast error — {exc}"

        if tokens_in < 0 or tokens_out < 0 or latency_ms < 0:
            return None, f"{run_id}: negative numeric value"

        success_raw = raw.get("success", "").strip().lower()
        if success_raw not in ("true", "false", "1", "0", "yes", "no"):
            return None, f"{run_id}: unrecognised success value '{success_raw}'"
        success = success_raw in ("true", "1", "yes")

        error_field = (raw.get("error") or "").strip()

        # Derived fields
        total_tokens = tokens_in + tokens_out
        cost_per_token = (cost_usd / total_tokens) if total_tokens > 0 else 0.0
        date_str = ts.strftime("%Y-%m-%d")

        return {
            "run_id":         run_id,
            "timestamp":      ts.isoformat(),
            "date":           date_str,
            "agent":          raw.get("agent", "").strip(),
            "provider":       raw.get("provider", "").strip(),
            "model":          raw.get("model", "").strip(),
            "task_type":      raw.get("task_type", "").strip(),
            "tokens_in":      tokens_in,
            "tokens_out":     tokens_out,
            "total_tokens":   total_tokens,
            "latency_ms":     latency_ms,
            "latency_s":      round(latency_ms / 1000, 3),
            "success":        success,
            "cost_usd":       cost_usd,
            "cost_per_token": round(cost_per_token, 8),
            "error":          error_field,
        }, ""

    # ── Aggregation ───────────────────────────────────────────────────────────

    @staticmethod
    def _mean(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    def _aggregate(self, rows: list[dict]) -> dict[str, Any]:
        if not rows:
            return {}

        total = len(rows)
        successes = [r for r in rows if r["success"]]
        failures  = [r for r in rows if not r["success"]]

        def _group(key: str) -> dict[str, list[dict]]:
            groups: dict[str, list[dict]] = {}
            for r in rows:
                groups.setdefault(r[key], []).append(r)
            return groups

        def _stats(group: list[dict]) -> dict:
            latencies  = [r["latency_ms"]  for r in group]
            costs      = [r["cost_usd"]    for r in group]
            tokens     = [r["total_tokens"] for r in group]
            return {
                "runs":           len(group),
                "success_rate":   round(sum(1 for r in group if r["success"]) / len(group), 4),
                "avg_latency_ms": round(self._mean(latencies), 1),
                "avg_cost_usd":   round(self._mean(costs), 6),
                "total_cost_usd": round(sum(costs), 6),
                "avg_tokens":     round(self._mean(tokens), 1),
                "total_tokens":   sum(tokens),
            }

        by_agent    = {k: _stats(v) for k, v in _group("agent").items()}
        by_provider = {k: _stats(v) for k, v in _group("provider").items()}
        by_task     = {k: _stats(v) for k, v in _group("task_type").items()}
        by_date     = {k: _stats(v) for k, v in _group("date").items()}

        # Top 3 costliest runs
        costliest = sorted(rows, key=lambda r: r["cost_usd"], reverse=True)[:3]

        return {
            "total_runs":       total,
            "successful_runs":  len(successes),
            "failed_runs":      len(failures),
            "overall_success_rate": round(len(successes) / total, 4),
            "total_cost_usd":   round(sum(r["cost_usd"]    for r in rows), 6),
            "total_tokens":     sum(r["total_tokens"] for r in rows),
            "avg_latency_ms":   round(self._mean([r["latency_ms"] for r in rows]), 1),
            "by_agent":         by_agent,
            "by_provider":      by_provider,
            "by_task_type":     by_task,
            "by_date":          by_date,
            "costliest_runs":   [
                {"run_id": r["run_id"], "agent": r["agent"],
                 "cost_usd": r["cost_usd"], "task_type": r["task_type"]}
                for r in costliest
            ],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Export
# ─────────────────────────────────────────────────────────────────────────────

class ExportStage:
    """Write cleaned rows and aggregate summary to disk."""

    def run(
        self,
        rows: list[dict],
        aggregates: dict[str, Any],
        source_path: Path,
        output_format: str = "csv",
    ) -> Path:
        """
        Writes two files to data/processed/<stem>_clean.<ext> and
        data/exports/<stem>_summary_<timestamp>.json.
        Returns the path to the clean data file.
        """
        _DEFAULT_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        _DEFAULT_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

        stem = source_path.stem
        ts   = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        # ── Write clean data ──────────────────────────────────────────────────
        output_format = (output_format or "csv").strip().lower()
        if output_format == "jsonl":
            clean_path = _DEFAULT_PROCESSED_DIR / f"{stem}_clean.jsonl"
            lines = [json.dumps(r, ensure_ascii=False) for r in rows]
            clean_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            clean_path = _DEFAULT_PROCESSED_DIR / f"{stem}_clean.csv"
            if rows:
                with clean_path.open("w", newline="", encoding="utf-8") as fh:
                    writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                    writer.writeheader()
                    writer.writerows(rows)

        # ── Write summary JSON ────────────────────────────────────────────────
        summary_path = _DEFAULT_EXPORTS_DIR / f"{stem}_summary_{ts}.json"
        summary_path.write_text(
            json.dumps(aggregates, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        logger.info("Export: clean data → %s", clean_path)
        logger.info("Export: summary    → %s", summary_path)
        return clean_path


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

class DataPipeline:
    """
    Orchestrates Ingest → Process → Export.

    Example::

        from core.data_pipeline import DataPipeline

        result = DataPipeline().run("data/raw/agent_runs.csv")
        if result.errors:
            print("Pipeline errors:", result.errors)
        else:
            print(result.summary)
    """

    def __init__(
        self,
        ingest:  IngestStage  | None = None,
        process: ProcessStage | None = None,
        export:  ExportStage  | None = None,
    ) -> None:
        self._ingest  = ingest  or IngestStage()
        self._process = process or ProcessStage()
        self._export  = export  or ExportStage()

    def run(
        self,
        source: str | Path = _DEFAULT_INPUT,
        output_format: str = "csv",
    ) -> PipelineResult:
        result = PipelineResult()
        source = Path(source)

        # Stage 1 — Ingest
        rows, ingest_errors = self._ingest.run(source)
        result.errors.extend(ingest_errors)
        if not rows:
            return result
        result.raw_rows = len(rows)

        # Stage 2 — Process
        clean, aggregates, drop_reasons = self._process.run(rows)
        result.clean_rows   = len(clean)
        result.dropped_rows = len(drop_reasons)
        result.summary      = aggregates
        result.errors.extend(drop_reasons)

        # Stage 3 — Export
        if clean:
            result.output_path = self._export.run(
                clean, aggregates, source, output_format
            )

        return result


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def _cli() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    parser = argparse.ArgumentParser(
        description="AetheerAI Data Pipeline — Ingest → Process → Export",
    )
    parser.add_argument(
        "--input", "-i",
        default=str(_DEFAULT_INPUT),
        metavar="FILE",
        help=f"CSV file to process (default: {_DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["csv", "jsonl"],
        default="csv",
        metavar="FMT",
        dest="output_format",
        help="Output format for processed data: csv (default) or jsonl",
    )
    args = parser.parse_args()

    pipeline = DataPipeline()
    result   = pipeline.run(source=args.input, output_format=args.output_format)

    print()
    print("=" * 60)
    print("  AetheerAI Data Pipeline — Results")
    print("=" * 60)
    print(f"  Input file   : {args.input}")
    print(f"  Raw rows     : {result.raw_rows}")
    print(f"  Clean rows   : {result.clean_rows}")
    print(f"  Dropped rows : {result.dropped_rows}")
    if result.output_path:
        print(f"  Output       : {result.output_path}")
    print()

    if result.summary:
        s = result.summary
        print(f"  Total runs         : {s.get('total_runs', 0)}")
        print(f"  Success rate       : {s.get('overall_success_rate', 0):.1%}")
        print(f"  Total cost (USD)   : ${s.get('total_cost_usd', 0):.4f}")
        print(f"  Total tokens       : {s.get('total_tokens', 0):,}")
        print(f"  Avg latency (ms)   : {s.get('avg_latency_ms', 0):.0f}")
        print()
        print("  By provider:")
        for prov, stats in sorted(s.get("by_provider", {}).items()):
            print(f"    {prov:<20} {stats['runs']:>3} runs  "
                  f"${stats['total_cost_usd']:.4f} total  "
                  f"{stats['avg_latency_ms']:.0f} ms avg")
        print()
        print("  By agent:")
        for agent, stats in sorted(s.get("by_agent", {}).items()):
            print(f"    {agent:<22} {stats['runs']:>3} runs  "
                  f"{stats['success_rate']:.0%} success")

    if result.errors:
        print()
        drop_msgs = [e for e in result.errors if ":" in e]
        if drop_msgs:
            print(f"  Dropped ({len(drop_msgs)}):")
            for msg in drop_msgs:
                print(f"    ⚠  {msg}")

    print()
    print("=" * 60)


if __name__ == "__main__":
    _cli()
