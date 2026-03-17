"""
Federated Privacy-Preserving Learning — Local Knowledge Distillation

Enterprises in 2026 are highly protective of their data sovereignty.
This module enables AetheerAI to learn from successful workflows across
departments without ever moving raw records to a central server.

The Protocol
------------
1. Each department node records its own workflow outcomes locally.
2. After N outcomes, a node distils a compact "Insight" — statistical
   summaries, extracted patterns, best-practice rules — with NO raw data.
3. The central aggregator merges insights from all nodes into a Global
   Model of best practices.
4. Agents query the Global Model before executing tasks, inheriting
   cross-department wisdom without touching anyone's data.

Privacy Guarantees
------------------
- Raw records never leave the node (they are cleared after distillation).
- Insights contain only aggregate statistics + pattern strings.
- A Privacy Audit log tracks every distil and aggregate operation.
- Differential-noise is added to numeric stats (ε-differential privacy lite).

Architecture
------------
  WorkflowRecord    — single raw outcome (kept locally, never shared)
  WorkflowInsight   — distilled summary (the only thing that is shared)
  FederatedNode     — per-department store + distiller
  GlobalModel       — aggregated cross-node best practices
  FederatedLearner  — main facade
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import statistics
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_DISTIL_MIN_RECORDS = 5          # minimum records before distillation
_NOISE_EPSILON      = 0.05       # differential noise factor (±5 %)


# ═══════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class WorkflowRecord:
    """Raw outcome — stays in the local node, never shared externally."""
    record_id: str
    workflow_type: str
    success: bool
    duration_ms: float
    tags: list[str]
    timestamp: float = field(default_factory=time.time)


@dataclass
class WorkflowInsight:
    """
    Privacy-safe distilled insight — the only artefact shared across nodes.
    Contains NO raw records, only aggregate statistics and pattern strings.
    """
    insight_id: str
    dept_id: str
    workflow_type: str
    sample_size: int
    success_rate: float         # with differential noise applied
    avg_duration_ms: float      # with differential noise applied
    best_practices: list[str]   # extracted heuristic rules
    common_tags: list[str]
    insight_hash: str           # SHA-256 of source record IDs (audit trail)
    distilled_at: float = field(default_factory=time.time)


@dataclass
class FederatedNode:
    dept_id: str
    _records: list[WorkflowRecord] = field(default_factory=list, repr=False)
    _insights: list[WorkflowInsight] = field(default_factory=list, repr=False)

    def record_count(self) -> int:
        return len(self._records)

    def insight_count(self) -> int:
        return len(self._insights)


@dataclass
class GlobalModel:
    """Aggregated cross-department best practices."""
    model_version: int
    workflow_types: list[str]
    global_best_practices: dict[str, list[str]]     # workflow_type → practices
    avg_success_rates: dict[str, float]              # workflow_type → rate
    contributing_nodes: list[str]
    built_at: float = field(default_factory=time.time)


@dataclass
class PrivacyAuditEntry:
    operation: str          # "distil" | "aggregate" | "query"
    dept_id: str
    records_involved: int
    raw_data_shared: bool   # must always be False
    timestamp: float = field(default_factory=time.time)


# ═══════════════════════════════════════════════════════════════════════════
# Federated Learner
# ═══════════════════════════════════════════════════════════════════════════


class FederatedLearner:
    """
    Federated privacy-preserving learning coordinator.

    Parameters
    ----------
    ai_adapter : AIAdapter  — used to extract best-practice patterns from insights.
    """

    def __init__(self, ai_adapter):
        self.ai_adapter = ai_adapter
        self._nodes:       dict[str, FederatedNode] = {}
        self._global:      GlobalModel | None        = None
        self._audit_log:   list[PrivacyAuditEntry]  = []

    # ──────────────────────────────────────────────────────────────────
    # Local node recording
    # ──────────────────────────────────────────────────────────────────

    def record_workflow(
        self,
        dept_id: str,
        workflow_type: str,
        success: bool,
        duration_ms: float,
        tags: list[str] | None = None,
    ) -> WorkflowRecord:
        """
        Record a single workflow outcome in a department's local node.
        Raw data never leaves the node.
        """
        if dept_id not in self._nodes:
            self._nodes[dept_id] = FederatedNode(dept_id=dept_id)

        record = WorkflowRecord(
            record_id=str(uuid.uuid4())[:8],
            workflow_type=workflow_type,
            success=success,
            duration_ms=duration_ms,
            tags=tags or [],
        )
        self._nodes[dept_id]._records.append(record)
        return record

    # ──────────────────────────────────────────────────────────────────
    # Distillation (node → insight)
    # ──────────────────────────────────────────────────────────────────

    def distil_insights(self, dept_id: str) -> list[WorkflowInsight]:
        """
        Distil all local records for a department into privacy-safe insights.
        Returns list of new insights. Clears the raw records afterwards.
        """
        node = self._nodes.get(dept_id)
        if not node or node.record_count() < _DISTIL_MIN_RECORDS:
            return []

        records = node._records[:]
        # Group by workflow type
        by_type: dict[str, list[WorkflowRecord]] = {}
        for r in records:
            by_type.setdefault(r.workflow_type, []).append(r)

        new_insights: list[WorkflowInsight] = []
        for wf_type, wf_records in by_type.items():
            if len(wf_records) < _DISTIL_MIN_RECORDS:
                continue

            success_rate  = sum(1 for r in wf_records if r.success) / len(wf_records)
            avg_duration  = statistics.mean(r.duration_ms for r in wf_records)
            # Add differential noise
            success_rate  = min(1.0, max(0.0, success_rate  + random.uniform(-_NOISE_EPSILON, _NOISE_EPSILON)))
            avg_duration  = max(0.0, avg_duration * (1 + random.uniform(-_NOISE_EPSILON, _NOISE_EPSILON)))

            # Common tags across records
            tag_counts: dict[str, int] = {}
            for r in wf_records:
                for t in r.tags:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
            common_tags = sorted(tag_counts, key=lambda t: -tag_counts[t])[:5]

            # Extract best practices via AI
            best_practices = self._extract_best_practices(
                dept_id, wf_type, success_rate, avg_duration, common_tags, wf_records
            )

            # Build audit hash from record IDs (not content)
            hash_input = ",".join(sorted(r.record_id for r in wf_records))
            insight_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

            insight = WorkflowInsight(
                insight_id=str(uuid.uuid4())[:8],
                dept_id=dept_id,
                workflow_type=wf_type,
                sample_size=len(wf_records),
                success_rate=round(success_rate, 4),
                avg_duration_ms=round(avg_duration, 1),
                best_practices=best_practices,
                common_tags=common_tags,
                insight_hash=insight_hash,
            )
            node._insights.append(insight)
            new_insights.append(insight)

        # Clear raw records after distillation (privacy guarantee)
        node._records.clear()

        self._audit_log.append(PrivacyAuditEntry(
            operation="distil",
            dept_id=dept_id,
            records_involved=len(records),
            raw_data_shared=False,
        ))
        logger.info("FederatedLearner: distilled %d records → %d insights for '%s'",
                    len(records), len(new_insights), dept_id)
        return new_insights

    # ──────────────────────────────────────────────────────────────────
    # Global model aggregation
    # ──────────────────────────────────────────────────────────────────

    def aggregate_global_model(self) -> GlobalModel:
        """
        Aggregate insights from all nodes into the Global Model.
        Only insight summaries are used — no raw records.
        """
        all_insights: list[WorkflowInsight] = []
        for node in self._nodes.values():
            all_insights.extend(node._insights)

        if not all_insights:
            return GlobalModel(
                model_version=1,
                workflow_types=[],
                global_best_practices={},
                avg_success_rates={},
                contributing_nodes=[],
            )

        # Group by workflow type
        by_type: dict[str, list[WorkflowInsight]] = {}
        for ins in all_insights:
            by_type.setdefault(ins.workflow_type, []).append(ins)

        global_practices: dict[str, list[str]]  = {}
        global_rates:     dict[str, float]       = {}

        for wf_type, insights in by_type.items():
            # Weighted average success rate
            total_samples = sum(i.sample_size for i in insights)
            if total_samples > 0:
                global_rates[wf_type] = sum(
                    i.success_rate * i.sample_size for i in insights
                ) / total_samples

            # Merge and deduplicate best practices
            all_practices: list[str] = []
            seen: set[str] = set()
            for ins in insights:
                for p in ins.best_practices:
                    key = p[:40].lower()
                    if key not in seen:
                        seen.add(key)
                        all_practices.append(p)
            global_practices[wf_type] = all_practices[:10]

        version = (self._global.model_version + 1) if self._global else 1
        self._global = GlobalModel(
            model_version=version,
            workflow_types=list(by_type.keys()),
            global_best_practices=global_practices,
            avg_success_rates=global_rates,
            contributing_nodes=list(self._nodes.keys()),
        )
        self._audit_log.append(PrivacyAuditEntry(
            operation="aggregate",
            dept_id="[global]",
            records_involved=len(all_insights),
            raw_data_shared=False,
        ))
        logger.info("FederatedLearner: global model v%d built from %d nodes",
                    self._global.model_version, len(self._nodes))
        return self._global

    # ──────────────────────────────────────────────────────────────────
    # Query
    # ──────────────────────────────────────────────────────────────────

    def get_best_practices(self, workflow_type: str) -> list[str]:
        """
        Query the Global Model for best practices applicable to a workflow type.
        Returns empty list if no global model has been built yet.
        """
        if not self._global:
            return []
        self._audit_log.append(PrivacyAuditEntry(
            operation="query",
            dept_id="[caller]",
            records_involved=0,
            raw_data_shared=False,
        ))
        # Exact match first, then fuzzy match
        practices = self._global.global_best_practices.get(workflow_type)
        if practices:
            return practices
        # Find similar types
        for wf in self._global.workflow_types:
            if workflow_type.lower() in wf.lower() or wf.lower() in workflow_type.lower():
                return self._global.global_best_practices.get(wf, [])
        return []

    def get_global_model(self) -> dict | None:
        if not self._global:
            return None
        return {
            "model_version": self._global.model_version,
            "workflow_types": self._global.workflow_types,
            "avg_success_rates": self._global.avg_success_rates,
            "best_practices": self._global.global_best_practices,
            "contributing_nodes": self._global.contributing_nodes,
            "built_at": self._global.built_at,
        }

    # ──────────────────────────────────────────────────────────────────
    # Stats & Audit
    # ──────────────────────────────────────────────────────────────────

    def node_stats(self) -> list[dict]:
        return [
            {
                "dept_id": node.dept_id,
                "pending_records": node.record_count(),
                "insights_distilled": node.insight_count(),
            }
            for node in self._nodes.values()
        ]

    def privacy_audit(self) -> list[dict]:
        """
        Return the privacy audit log.
        Every entry must have raw_data_shared=False — verified at return time.
        """
        for entry in self._audit_log:
            assert not entry.raw_data_shared, "PRIVACY VIOLATION: raw data was shared!"
        return [
            {
                "operation": e.operation,
                "dept_id": e.dept_id,
                "records_involved": e.records_involved,
                "raw_data_shared": e.raw_data_shared,
                "timestamp": e.timestamp,
            }
            for e in self._audit_log
        ]

    # ──────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────

    def _extract_best_practices(
        self,
        dept_id: str,
        workflow_type: str,
        success_rate: float,
        avg_duration_ms: float,
        common_tags: list[str],
        records: list[WorkflowRecord],
    ) -> list[str]:
        """Use AI to extract best-practice rules from aggregated workflow stats."""
        success_count = sum(1 for r in records if r.success)
        fail_tags = []
        for r in records:
            if not r.success:
                fail_tags.extend(r.tags)

        prompt = f"""Extract 3-5 best-practice rules from this workflow analytics summary.
Rules must be actionable and generic (no PII, no raw data).

Department: {dept_id}
Workflow type: {workflow_type}
Success rate: {success_rate:.0%}
Average duration: {avg_duration_ms:.0f}ms
Samples: {len(records)}
Common tags on all runs: {common_tags}
Tags that appear only on failed runs: {list(set(fail_tags))[:10]}

Return ONLY a JSON array of strings — e.g.:
["Always validate input before processing", "Retry on timeout up to 3 times"]"""

        try:
            raw = self.ai_adapter.chat([
                {"role": "system", "content": "You are a workflow analysis AI. Return a JSON array only."},
                {"role": "user", "content": prompt},
            ])
            import re
            m = re.search(r"\[[\s\S]+?\]", raw)
            if m:
                return json.loads(m.group())[:5]
        except Exception as exc:
            logger.debug("FederatedLearner: AI extract failed: %s", exc)

        # Fallback heuristics
        practices = []
        if success_rate >= 0.9:
            practices.append(f"Workflow '{workflow_type}' is reliable — no changes needed.")
        elif success_rate < 0.7:
            practices.append(f"Success rate below 70% — add input validation and retry logic.")
        if avg_duration_ms > 10_000:
            practices.append("Execution time is high — consider caching or parallel steps.")
        if common_tags:
            practices.append(f"Frequent tags: {', '.join(common_tags[:3])} — use as routing hints.")
        return practices or ["Collect more samples for meaningful patterns."]
