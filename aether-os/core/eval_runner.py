"""Lightweight evaluation runner for iterative quality checks."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable


@dataclass
class EvalCaseResult:
    id: str
    passed: bool
    output: str
    expected_contains: str | None
    error: str | None
    latency_ms: float


class EvalRunner:
    """Executes eval cases through a supplied callable."""

    def run_cases(
        self,
        cases: list[dict[str, Any]],
        run_fn: Callable[[str], str],
    ) -> dict[str, Any]:
        results: list[EvalCaseResult] = []

        for idx, case in enumerate(cases, start=1):
            case_id = str(case.get("id") or f"case_{idx}")
            prompt = str(case.get("prompt") or "")
            expected = case.get("expected_contains")
            expected_text = str(expected) if expected is not None else None

            start = perf_counter()
            output = ""
            error = None
            passed = False
            try:
                output = str(run_fn(prompt))
                if expected_text is None:
                    passed = bool(output.strip())
                else:
                    passed = expected_text.lower() in output.lower()
            except Exception as exc:
                error = str(exc)
            latency_ms = (perf_counter() - start) * 1000.0

            results.append(
                EvalCaseResult(
                    id=case_id,
                    passed=passed,
                    output=output,
                    expected_contains=expected_text,
                    error=error,
                    latency_ms=latency_ms,
                )
            )

        total = len(results)
        passed_count = sum(1 for r in results if r.passed)
        failed_count = total - passed_count
        avg_latency_ms = (sum(r.latency_ms for r in results) / total) if total else 0.0

        return {
            "total": total,
            "passed": passed_count,
            "failed": failed_count,
            "pass_rate": (passed_count / total) if total else 0.0,
            "avg_latency_ms": avg_latency_ms,
            "results": [r.__dict__ for r in results],
        }
