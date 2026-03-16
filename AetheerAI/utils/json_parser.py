"""
json_parser.py — Robust JSON extraction from LLM responses.

Replaces fragile regex hacks throughout the kernel with a single, reliable
extractor that handles:
  • Clean JSON ("{ ... }")
  • Fenced code blocks  ```json ... ``` or ``` ... ```
  • Trailing commas before closing brackets (common LLM hallucination)
  • Surrounding conversational text

Usage
-----
    from utils.json_parser import extract_json, ParseError

    data = extract_json(llm_response)          # raises ParseError on failure
    data = extract_json(llm_response, safe=True)  # returns {} on failure
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class ParseError(ValueError):
    """Raised when no valid JSON object can be extracted from text."""


# ── Pre-compiled patterns ─────────────────────────────────────────────────────

# Match a fenced code block (with or without language tag)
_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```",
    re.DOTALL | re.IGNORECASE,
)

# Match the outermost JSON object (non-greedy is NOT suitable here — use greedy
# with brace counting instead; but a greedy dotall pattern works for most cases)
_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_ARRAY_RE  = re.compile(r"\[.*\]",  re.DOTALL)

# Remove trailing commas before } or ] — a common LLM mistake
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _clean(text: str) -> str:
    """Strip markdown fences and trailing commas."""
    # Remove fences
    text = re.sub(r"```(?:json)?|```", "", text)
    # Remove trailing commas
    text = _TRAILING_COMMA_RE.sub(r"\1", text)
    return text.strip()


def _try_parse(text: str) -> dict[str, Any] | list[Any]:
    """Attempt json.loads; raise ParseError with a helpful message on failure."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError(f"JSON decode error: {exc}") from exc


def extract_json(
    text: str,
    *,
    safe: bool = False,
    default: Any = None,
) -> Any:
    """
    Extract and parse the first JSON object or array from *text*.

    Parameters
    ----------
    text    : Raw LLM response string.
    safe    : If True, never raise — return *default* on failure.
    default : Value returned when safe=True and parsing fails (default: {}).

    Returns
    -------
    Parsed dict or list.

    Raises
    ------
    ParseError  — only when safe=False (default).
    """
    if default is None:
        default = {}

    if not text or not isinstance(text, str):
        if safe:
            return default
        raise ParseError("Input is empty or not a string.")

    text = text.strip()

    # ── Attempt 1: try parsing the whole text directly ────────────────
    cleaned = _clean(text)
    try:
        return _try_parse(cleaned)
    except ParseError:
        pass

    # ── Attempt 2: extract from fenced block ─────────────────────────
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        try:
            candidate = _clean(fence_match.group(1))
            return _try_parse(candidate)
        except ParseError:
            pass

    # ── Attempt 3: find the outermost { ... } ────────────────────────
    obj_match = _OBJECT_RE.search(cleaned)
    if obj_match:
        try:
            return _try_parse(obj_match.group())
        except ParseError:
            pass

    # ── Attempt 4: find the outermost [ ... ] ────────────────────────
    arr_match = _ARRAY_RE.search(cleaned)
    if arr_match:
        try:
            return _try_parse(arr_match.group())
        except ParseError:
            pass

    # ── All attempts failed ───────────────────────────────────────────
    logger.warning("extract_json: could not parse JSON from LLM response (len=%d)", len(text))
    if safe:
        return default
    raise ParseError(
        f"Could not extract valid JSON from LLM response. "
        f"First 200 chars: {text[:200]!r}"
    )
