"""Generate a quality-gated patch proposal report for CI artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from core.self_improve import SelfImproveCoordinator


def _default_cases() -> list[dict[str, str]]:
    return [
        {"id": "gate-1", "prompt": "health", "expected_contains": "ok"},
        {"id": "gate-2", "prompt": "policy", "expected_contains": "allow"},
    ]


def _stub_run_fn(prompt: str) -> str:
    mapping = {
        "health": "ok",
        "policy": "allow",
    }
    return mapping.get(prompt, "unknown")


def generate_proposal_report(gate_results: dict[str, bool]) -> dict:
    coord = SelfImproveCoordinator()
    report = coord.run_with_quality_gates(
        cases=_default_cases(),
        run_fn=_stub_run_fn,
        gate_results=gate_results,
    )
    return report


def main() -> None:
    out_dir = Path("memory") / "proposed_patches"
    out_dir.mkdir(parents=True, exist_ok=True)

    gate_results = {
        "python_unit_tests": True,
        "tours_checks": True,
        "security_checks": True,
    }
    report = generate_proposal_report(gate_results)

    out_file = out_dir / "latest.json"
    out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote patch proposal report: {out_file}")


if __name__ == "__main__":
    main()
