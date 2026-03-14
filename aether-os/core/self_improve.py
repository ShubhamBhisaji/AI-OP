"""Coordinator for one-step self-improvement loops."""

from __future__ import annotations

from typing import Any, Callable

from evals.benchmark_runner import BenchmarkRunner
from evals.failure_clustering import cluster_failures


class SelfImproveCoordinator:
    def __init__(self, eval_runner: BenchmarkRunner | None = None) -> None:
        self.eval_runner = eval_runner or BenchmarkRunner()

    def run_once(
        self,
        cases: list[dict[str, Any]],
        run_fn: Callable[[str], str],
    ) -> dict[str, Any]:
        summary = self.eval_runner.run_cases(cases, run_fn=run_fn)
        clusters = cluster_failures(summary.get("results", []))

        recommendations: list[str] = []
        for key, items in clusters.items():
            count = len(items)
            if key.startswith("error:"):
                recommendations.append(
                    f"Investigate runtime stability issue '{key}' ({count} failures)."
                )
            elif key.startswith("missing:"):
                recommendations.append(
                    f"Improve prompt/tooling for unmet expectation '{key[8:]}' ({count} failures)."
                )
            else:
                recommendations.append(
                    f"Review unclassified failure cluster '{key}' ({count} failures)."
                )

        return {
            "eval_summary": summary,
            "failure_clusters": clusters,
            "recommendations": recommendations,
        }
