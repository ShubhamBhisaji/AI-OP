"""Minimal local prediction model with a stable `predict(input_data)` API.

This gives the project a guaranteed working inference path even when no cloud
LLM key is configured. It starts as a simple heuristic model and can be
incrementally upgraded later without changing API contracts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LocalPredictor:
    """Simple local inference model used as fallback in `/predict`."""

    version: str = "dummy-v1"

    def predict(self, input_data: str) -> str:
        """Predict a result from raw text input data.

        Current behavior is intentionally simple and deterministic.
        """
        text = (input_data or "").strip()
        if not text:
            return "result"

        # Small, deterministic heuristic for an immediately useful baseline.
        if any(k in text.lower() for k in ("error", "fail", "exception", "bug")):
            return "Likely issue detected. Suggest: inspect logs and retry with narrower scope."
        if len(text) < 40:
            return f"Quick result: {text}"
        return "result"


def predict(input_data: str) -> str:
    """Function-form entrypoint requested by users.

    Example:
        predict("hello") -> "Quick result: hello"
    """
    return LocalPredictor().predict(input_data)
