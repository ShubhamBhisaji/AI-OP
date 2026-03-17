"""
SemanticPreprocessor — Automated Data Structuring for AI agents.

Agents fail when fed messy, unstructured data.  A PDF scan, a Zoom
transcript, or a screenshot treated as raw text leads to hallucinations
and mis-reads.  This pre-processor sits in front of every agent and turns
raw chaos into clean, machine-readable JSON or Markdown — guaranteed.

Supported input types
---------------------
  PDF text          → Structured JSON with sections, tables, key-values
  Audio transcript  → Speaker-attributed Q&A + action items
  Screenshot OCR    → Structured JSON from extracted text regions
  Raw HTML          → Clean Markdown
  Messy text        → Normalised, de-noised plain text
  CSV (unclean)     → Schema-inferred JSON
  Email             → Structured dict: subject, sender, date, body, action_items
  Product/JSON      → Validated, flattened JSON

Architecture
------------
  PreprocessorPipeline  — chains multiple cleaning steps
  SemanticPreprocessor  — main facade with named strategies per content-type
  CleanedDocument       — standard output container

Usage
-----
    pp = SemanticPreprocessor(ai_adapter)

    # Auto-detect and clean:
    doc = pp.clean(raw_text, hint="pdf")
    # doc.content_type  →  "pdf"
    # doc.structured    →  { "title": ..., "sections": [...], "tables": [...] }
    # doc.markdown      →  clean Markdown string
    # doc.ready_for_agent  →  True

    # Use in a pipeline (inject before running an agent):
    clean_doc = pp.clean(raw_pdf_text, hint="pdf")
    result = kernel.run_agent("AnalystAgent", clean_doc.to_agent_input())
"""

from __future__ import annotations

import json
import logging
import re
import textwrap
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Content type hints ────────────────────────────────────────────────────

CONTENT_TYPES = (
    "pdf",
    "transcript",
    "screenshot",
    "html",
    "email",
    "csv",
    "json",
    "text",
    "auto",
)

# ── Minimum quality thresholds ────────────────────────────────────────────

_MIN_CONTENT_LENGTH = 20     # reject documents shorter than this
_MAX_INPUT_CHARS = 40_000    # hard cap sent to AI (avoid token explosion)


# ═══════════════════════════════════════════════════════════════════════════
# Output container
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class CleanedDocument:
    original_length: int
    content_type: str
    structured: dict                # machine-readable JSON payload
    markdown: str                   # human-readable clean Markdown
    ready_for_agent: bool
    quality_score: float            # 0.0 – 1.0 (heuristic)
    warnings: list[str] = field(default_factory=list)
    processing_ms: float = 0.0

    def to_agent_input(self) -> str:
        """
        Return a compact agent-ready string combining structured JSON + markdown.
        Agents should be given this instead of raw input.
        """
        return (
            f"[STRUCTURED DATA — type: {self.content_type}]\n"
            f"```json\n{json.dumps(self.structured, indent=2)}\n```\n\n"
            f"[CLEAN TEXT]\n{self.markdown}"
        )

    def to_dict(self) -> dict:
        return {
            "content_type": self.content_type,
            "ready_for_agent": self.ready_for_agent,
            "quality_score": round(self.quality_score, 2),
            "original_length": self.original_length,
            "structured_keys": list(self.structured.keys()),
            "markdown_length": len(self.markdown),
            "warnings": self.warnings,
            "processing_ms": round(self.processing_ms, 1),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Semantic Preprocessor
# ═══════════════════════════════════════════════════════════════════════════


class SemanticPreprocessor:
    """
    AI-powered unstructured-data cleaner.

    Parameters
    ----------
    ai_adapter : AIAdapter — used to run the cleaning/structuring prompts.
    max_input_chars : Hard cap on characters sent to AI (default 40 000).
    """

    def __init__(self, ai_adapter, max_input_chars: int = _MAX_INPUT_CHARS):
        self.ai_adapter = ai_adapter
        self.max_input_chars = max_input_chars

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def clean(
        self,
        raw: str,
        hint: str = "auto",
        extra_instructions: str = "",
    ) -> CleanedDocument:
        """
        Clean and structure raw unstructured input.

        Parameters
        ----------
        raw                 : Raw content string (PDF text, transcript, etc.)
        hint                : Content type hint ("pdf", "transcript", "html",
                              "screenshot", "email", "csv", "json", "text", "auto").
        extra_instructions  : Optional extra instructions for the AI cleaner.

        Returns
        -------
        CleanedDocument — always returned; ready_for_agent=False if input too short.
        """
        t0 = time.time()
        warnings: list[str] = []

        if len(raw.strip()) < _MIN_CONTENT_LENGTH:
            return CleanedDocument(
                original_length=len(raw),
                content_type=hint,
                structured={},
                markdown="",
                ready_for_agent=False,
                quality_score=0.0,
                warnings=["Input too short to process."],
            )

        # Auto-detect type
        content_type = hint if hint != "auto" else self._detect_type(raw)

        # Truncate if needed
        truncated = raw[:self.max_input_chars]
        if len(raw) > self.max_input_chars:
            warnings.append(
                f"Input truncated from {len(raw):,} to {self.max_input_chars:,} chars."
            )

        # Dispatch to strategy
        try:
            structured, markdown = self._dispatch(content_type, truncated, extra_instructions)
        except Exception as exc:
            logger.warning("SemanticPreprocessor error: %s", exc)
            structured = {"raw": truncated}
            markdown = truncated
            warnings.append(f"AI structuring failed ({exc}); returning raw text.")

        quality = self._score_quality(structured, markdown)

        return CleanedDocument(
            original_length=len(raw),
            content_type=content_type,
            structured=structured,
            markdown=markdown,
            ready_for_agent=quality > 0.3,
            quality_score=quality,
            warnings=warnings,
            processing_ms=(time.time() - t0) * 1000,
        )

    def clean_batch(self, items: list[dict]) -> list[CleanedDocument]:
        """
        Clean multiple documents. Each item is a dict with keys:
            raw, hint (optional), extra_instructions (optional).
        """
        return [
            self.clean(
                item["raw"],
                hint=item.get("hint", "auto"),
                extra_instructions=item.get("extra_instructions", ""),
            )
            for item in items
        ]

    # ──────────────────────────────────────────────────────────────────
    # Strategy dispatch
    # ──────────────────────────────────────────────────────────────────

    def _dispatch(
        self, content_type: str, raw: str, extra: str
    ) -> tuple[dict, str]:
        strategies = {
            "pdf":        self._clean_pdf,
            "transcript": self._clean_transcript,
            "screenshot": self._clean_screenshot,
            "html":       self._clean_html,
            "email":      self._clean_email,
            "csv":        self._clean_csv,
            "json":       self._clean_json_doc,
            "text":       self._clean_text,
        }
        fn = strategies.get(content_type, self._clean_text)
        return fn(raw, extra)

    # ──────────────────────────────────────────────────────────────────
    # Individual strategies
    # ──────────────────────────────────────────────────────────────────

    def _clean_pdf(self, raw: str, extra: str) -> tuple[dict, str]:
        prompt = f"""You are a data-structuring AI.  Extract clean information from this PDF text.

{('Extra instructions: ' + extra) if extra else ''}

PDF text:
---
{raw}
---

Return ONLY valid JSON in this exact format:
{{
  "title": "<document title>",
  "summary": "<2-3 sentence summary>",
  "sections": [{{"heading": "...", "content": "..."}}],
  "key_values": {{"key": "value"}},
  "tables": [{{"headers": ["col1"], "rows": [["val1"]]}}],
  "action_items": ["<item>"],
  "dates": ["<date>"],
  "entities": ["<person/org/place>"]
}}"""
        return self._run_and_parse(prompt, raw)

    def _clean_transcript(self, raw: str, extra: str) -> tuple[dict, str]:
        prompt = f"""You are a meeting-intelligence AI.  Structure this conversation transcript.

{('Extra instructions: ' + extra) if extra else ''}

Transcript:
---
{raw}
---

Return ONLY valid JSON:
{{
  "participants": ["<name>"],
  "summary": "<2-3 sentences>",
  "topics": ["<topic>"],
  "decisions": ["<decision>"],
  "action_items": [{{"owner": "<name>", "task": "<task>", "due": "<date or null>"}}],
  "key_quotes": [{{"speaker": "...", "quote": "..."}}]
}}"""
        return self._run_and_parse(prompt, raw)

    def _clean_screenshot(self, raw: str, extra: str) -> tuple[dict, str]:
        prompt = f"""You are an OCR post-processor.  The following is raw text extracted from a screenshot.
Clean it up and extract structured data.

{('Extra instructions: ' + extra) if extra else ''}

Raw OCR text:
---
{raw}
---

Return ONLY valid JSON:
{{
  "screen_type": "<e.g. dashboard, form, email, webpage>",
  "title": "<inferred title>",
  "text_blocks": ["<clean text block>"],
  "key_values": {{"label": "value"}},
  "buttons_links": ["<visible UI elements>"],
  "numbers": ["<any numbers or metrics>"],
  "summary": "<what this screen shows>"
}}"""
        return self._run_and_parse(prompt, raw)

    def _clean_html(self, raw: str, extra: str) -> tuple[dict, str]:
        # Fast local HTML stripping first
        text = re.sub(r"<script[\s\S]*?</script>", "", raw, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        if len(text) < 100:
            return {"raw_html_stripped": text}, text

        prompt = f"""Convert this web page text into clean, structured Markdown.
Remove navigation, ads, footers. Keep: headings, body text, links, tables.

{('Extra instructions: ' + extra) if extra else ''}

Text:
---
{text[:self.max_input_chars]}
---

Return ONLY valid JSON:
{{
  "title": "<page title>",
  "main_content": "<clean main body markdown>",
  "headings": ["<h1>", "<h2>"],
  "links": [{{"text": "...", "note": "visible link text"}}],
  "summary": "<2 sentence summary>"
}}"""
        return self._run_and_parse(prompt, text)

    def _clean_email(self, raw: str, extra: str) -> tuple[dict, str]:
        prompt = f"""Extract structured data from this email.

{('Extra instructions: ' + extra) if extra else ''}

Email:
---
{raw}
---

Return ONLY valid JSON:
{{
  "subject": "<subject>",
  "from": "<sender>",
  "to": ["<recipient>"],
  "date": "<date>",
  "body_clean": "<clean body text>",
  "sentiment": "positive|neutral|negative|urgent",
  "action_items": ["<required action>"],
  "attachments_mentioned": ["<filename>"],
  "key_data": {{"key": "value"}}
}}"""
        return self._run_and_parse(prompt, raw)

    def _clean_csv(self, raw: str, extra: str) -> tuple[dict, str]:
        import csv
        import io
        try:
            reader = csv.DictReader(io.StringIO(raw))
            rows = [dict(r) for r in reader]
            headers = list(rows[0].keys()) if rows else []
            structured = {
                "headers": headers,
                "row_count": len(rows),
                "sample_rows": rows[:10],
                "schema": {h: self._infer_type(rows, h) for h in headers},
            }
            markdown = f"CSV — {len(rows)} rows × {len(headers)} columns\n\n"
            markdown += "| " + " | ".join(headers) + " |\n"
            markdown += "| " + " | ".join(["---"] * len(headers)) + " |\n"
            for row in rows[:20]:
                markdown += "| " + " | ".join(str(row.get(h, "")) for h in headers) + " |\n"
            return structured, markdown
        except Exception:
            return {"raw_csv": raw}, raw

    def _clean_json_doc(self, raw: str, extra: str) -> tuple[dict, str]:
        # Try to parse as-is first
        try:
            match = re.search(r"[\[\{][\s\S]+[\]\}]", raw)
            if match:
                parsed = json.loads(match.group())
                md = f"```json\n{json.dumps(parsed, indent=2)}\n```"
                return {"parsed": parsed, "valid": True}, md
        except Exception:
            pass

        prompt = f"""Fix and parse this malformed JSON.

{('Extra instructions: ' + extra) if extra else ''}

Input:
---
{raw}
---

Return ONLY valid JSON:
{{
  "fixed_json": <the corrected JSON object here>,
  "issues_found": ["<description of fix made>"]
}}"""
        return self._run_and_parse(prompt, raw)

    def _clean_text(self, raw: str, extra: str) -> tuple[dict, str]:
        prompt = f"""Clean and normalise this raw text for downstream AI processing.

{('Extra instructions: ' + extra) if extra else ''}

Raw text:
---
{raw}
---

Return ONLY valid JSON:
{{
  "title": "<inferred title if any>",
  "clean_text": "<de-noised, normalised text without OCR artifacts>",
  "key_points": ["<main point>"],
  "entities": ["<names, dates, organisations>"],
  "language": "<ISO 639-1 code>",
  "summary": "<1 sentence>"
}}"""
        return self._run_and_parse(prompt, raw)

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    def _run_and_parse(self, prompt: str, raw_fallback: str) -> tuple[dict, str]:
        """Call the AI, parse JSON result, return (structured, markdown)."""
        raw_response = self.ai_adapter.chat([
            {
                "role": "system",
                "content": (
                    "You are a data-structuring specialist. "
                    "Always respond with valid JSON only — no prose."
                ),
            },
            {"role": "user", "content": prompt},
        ])
        structured = self._extract_json(raw_response)
        markdown = self._json_to_markdown(structured)
        return structured, markdown

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract a JSON object from AI response text."""
        # Strip markdown fences
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
        if match:
            text = match.group(1)
        # Find JSON object or array
        for pattern in (r"\{[\s\S]+\}", r"\[[\s\S]+\]"):
            m = re.search(pattern, text)
            if m:
                try:
                    return json.loads(m.group())
                except json.JSONDecodeError:
                    pass
        # Last resort — return raw as text field
        return {"raw_response": text}

    @staticmethod
    def _json_to_markdown(data: dict) -> str:
        """Convert a structured dict to readable Markdown."""
        lines = []
        for key, val in data.items():
            if isinstance(val, str) and val:
                lines.append(f"**{key}**: {val}")
            elif isinstance(val, list) and val:
                lines.append(f"**{key}**:")
                for item in val:
                    if isinstance(item, dict):
                        entry = ", ".join(f"{k}: {v}" for k, v in item.items())
                        lines.append(f"  - {entry}")
                    else:
                        lines.append(f"  - {item}")
            elif isinstance(val, dict) and val:
                lines.append(f"**{key}**:")
                for k, v in val.items():
                    lines.append(f"  - {k}: {v}")
        return "\n".join(lines)

    @staticmethod
    def _infer_type(rows: list[dict], col: str) -> str:
        """Heuristic column type inference for CSV cleaner."""
        vals = [str(r.get(col, "")).strip() for r in rows[:20] if r.get(col)]
        if not vals:
            return "unknown"
        numeric = sum(1 for v in vals if re.match(r"^-?\d+\.?\d*$", v))
        if numeric / len(vals) > 0.8:
            return "numeric"
        if all(len(v) <= 10 and re.match(r"\d{1,4}[-/]\d{1,2}[-/]\d{1,4}", v) for v in vals[:5]):
            return "date"
        return "text"

    @staticmethod
    def _detect_type(raw: str) -> str:
        """Heuristic to auto-detect content type from raw text."""
        sample = raw[:2000].lower()
        if re.search(r"<html|<body|<!doctype", sample):
            return "html"
        if re.search(r'"from":|"subject":|^from:|^subject:', sample, re.MULTILINE):
            return "email"
        if sample.count("\n") > 10 and sample.count(",") > 20 and sample.split("\n")[0].count(",") > 2:
            return "csv"
        if re.search(r'^\s*[\{\[]', sample):
            return "json"
        if re.search(r'\b(speaker|participant|host|attendee)\b.*?:', sample):
            return "transcript"
        if re.search(r'\bpage \d+|\btable of contents\b|\bsection \d+\b', sample):
            return "pdf"
        return "text"

    @staticmethod
    def _score_quality(structured: dict, markdown: str) -> float:
        """Heuristic quality score 0–1."""
        score = 0.0
        if len(markdown) > 50:
            score += 0.3
        if len(structured) > 1:
            score += 0.3
        if "summary" in structured or "clean_text" in structured:
            score += 0.2
        if "raw" not in structured and "raw_response" not in structured:
            score += 0.2
        return min(1.0, score)

    @staticmethod
    def supported_types() -> list[str]:
        return list(CONTENT_TYPES)
