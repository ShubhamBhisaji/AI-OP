"""Lightweight evaluation runner for iterative quality checks."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
import threading
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

    _DEFAULT_CASE_TIMEOUT_S = 45.0
    _DEFAULT_MAX_CASES = 100
    _DEFAULT_MAX_TEXT_CHARS = 4000

    @staticmethod
    def _run_with_timeout(
        run_fn: Callable[[str], str],
        prompt: str,
        timeout_s: float,
    ) -> tuple[str, str | None]:
        q: Queue[tuple[str, str]] = Queue(maxsize=1)

        def _target() -> None:
            try:
                q.put(("ok", str(run_fn(prompt))))
            except Exception as exc:
                q.put(("err", str(exc)))

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(timeout_s)

        if t.is_alive():
            return "", f"Timeout after {timeout_s:.1f}s"

        try:
            status, value = q.get_nowait()
        except Empty:
            return "", "Eval runner produced no result"

        if status == "err":
            return "", value
        return value, None

    def run_cases(
        self,
        cases: list[dict[str, Any]],
        run_fn: Callable[[str], str],
        case_timeout_s: float | None = None,
        max_cases: int | None = None,
        max_text_chars: int | None = None,
    ) -> dict[str, Any]:
        timeout_s = float(case_timeout_s or self._DEFAULT_CASE_TIMEOUT_S)
        case_limit = int(max_cases or self._DEFAULT_MAX_CASES)
        text_limit = int(max_text_chars or self._DEFAULT_MAX_TEXT_CHARS)
        bounded_cases = cases[:case_limit]

        results: list[EvalCaseResult] = []

        for idx, case in enumerate(bounded_cases, start=1):
            case_id = str(case.get("id") or f"case_{idx}")
            prompt = str(case.get("prompt") or "")
            expected = case.get("expected_contains")
            expected_text = str(expected) if expected is not None else None

            start = perf_counter()
            output = ""
            error = None
            passed = False
            raw_output, raw_error = self._run_with_timeout(run_fn, prompt, timeout_s=timeout_s)
            output = raw_output
            error = raw_error
            if error is None:
                if expected_text is None:
                    passed = bool(raw_output.strip())
                else:
                    passed = expected_text.lower() in raw_output.lower()

            if len(output) > text_limit:
                output = output[:text_limit] + "... [truncated]"
            if error and len(error) > text_limit:
                error = error[:text_limit] + "... [truncated]"
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
            "case_timeout_s": timeout_s,
            "max_cases": case_limit,
            "truncated_cases": max(0, len(cases) - len(bounded_cases)),
            "results": [r.__dict__ for r in results],
        }
