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

    @staticmethod
    def _quality_gates_pass(gate_results: dict[str, bool]) -> tuple[bool, list[str]]:
        failed = [name for name, passed in gate_results.items() if not bool(passed)]
        return (len(failed) == 0, failed)

    def propose_patch(self, report: dict[str, Any], gate_results: dict[str, bool]) -> dict[str, Any]:
        allowed, failed = self._quality_gates_pass(gate_results)
        if not allowed:
            return {
                "allowed": False,
                "reason": "Quality gates failed",
                "failed_gates": failed,
                "proposal": [],
            }

        proposal = []
        for rec in report.get("recommendations", []):
            proposal.append({"action": "patch", "description": rec})

        return {
            "allowed": True,
            "reason": "All quality gates passed",
            "failed_gates": [],
            "proposal": proposal,
        }

    def run_with_quality_gates(
        self,
        cases: list[dict[str, Any]],
        run_fn: Callable[[str], str],
        gate_results: dict[str, bool],
    ) -> dict[str, Any]:
        report = self.run_once(cases=cases, run_fn=run_fn)
        report["quality_gates"] = dict(gate_results)
        report["patch_proposal"] = self.propose_patch(report, gate_results)
        return report
