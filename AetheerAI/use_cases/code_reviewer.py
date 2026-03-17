"""
use_cases/code_reviewer.py — CodeReviewer Use Case Pack.

Input  : path  (file or directory of Python source code)
Output : 1 file written alongside the source — code_review.md
           Sections:
             - Executive Summary   (overall quality score + 1-paragraph verdict)
             - Critical Bugs       (will crash or produce wrong output)
             - Security Issues     (OWASP-aligned; injection, secrets, etc.)
             - Performance         (algorithmic complexity, IO bottlenecks)
             - Code Style          (PEP 8, naming, readability)
             - Refactoring Targets (duplication, abstractions, dead code)
             - Quick Wins          (3–5 specific, copy-pasteable fix suggestions)

Agent pipeline
--------------
  1. Collector  — reads source files, builds a combined code context (respects sandbox)
  2. Analyst    — runs the full review prompt against the code context
  3. Writer     — structures output into the standard Markdown report template
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from use_cases.base import InputField, UseCase, UseCaseResult

logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = 120_000   # guard against accidentally feeding binary/huge files
_MAX_FILES = 40             # cap number of py files scanned per run
_MAX_CONTEXT_CHARS = 40_000 # soft cap for the AI context window

# ── Prompts ───────────────────────────────────────────────────────────────────

_REVIEW_PROMPT = """\
You are a Principal Software Engineer performing a thorough code review.

Source context
--------------
{code_context}

Produce a structured Markdown code-review report with EXACTLY these sections
(use ## headings):

## Executive Summary
Overall quality: <score 1–10>/10
<1-paragraph honest verdict>

## Critical Bugs
List specific line-level bugs that will crash or produce incorrect results.
Use format: `filename:line — description`
If none: write "None found."

## Security Issues
OWASP-aligned issues: injection flaws, hardcoded secrets, broken auth, SSRF, etc.
Format: `filename:line — issue — remediation`
If none: write "None found."

## Performance
Algorithmic complexity issues, unnecessary IO, N+1 queries, blocking calls.
If none: write "None found."

## Code Style
PEP 8 violations, naming issues, missing type hints where they'd add clarity.
Top 3–5 items only.

## Refactoring Targets
Duplication, large functions, missing abstractions, dead code.
Top 3–5 items.

## Quick Wins (copy-pasteable fixes)
Provide 3–5 EXACT before/after code snippets for the most impactful fixes.
Use fenced code blocks.

---
End of review. Be specific — cite file names and line numbers wherever possible.
"""


class CodeReviewer(UseCase):
    """
    Automated code-review report for any Python file or directory.

    One command → structured Markdown report with bugs, security issues,
    performance notes, style feedback, and copy-pasteable fixes.
    """

    @property
    def name(self) -> str:
        return "code_reviewer"

    @property
    def title(self) -> str:
        return "Code Reviewer"

    @property
    def description(self) -> str:
        return (
            "Automated PR-quality code review for any Python file or folder: "
            "bugs, security issues, performance, style, and ready-to-paste fixes."
        )

    @property
    def inputs(self) -> list[InputField]:
        return [
            InputField(
                name="path",
                description="Absolute or workspace-relative path to a Python file or directory.",
                required=True,
                example="src/api/server.py",
            ),
            InputField(
                name="focus",
                description=(
                    "Optional comma-separated focus areas to emphasise in the review. "
                    "Options: security, performance, style, bugs, all (default: all)"
                ),
                required=False,
                default="all",
                example="security,bugs",
            ),
        ]

    # ------------------------------------------------------------------

    def run(self, inputs: dict[str, Any], kernel) -> UseCaseResult:
        raw_path = inputs["path"].strip()
        focus: str = (inputs.get("focus") or "all").strip()

        # Resolve path relative to workspace root if not absolute
        target = Path(raw_path)
        if not target.is_absolute():
            workspace_root = Path(__file__).resolve().parents[2]
            target = workspace_root / target

        if not target.exists():
            return UseCaseResult(
                success=False,
                summary="",
                error=f"Path does not exist: {target}",
            )

        # ── Collect source files ──────────────────────────────────────
        py_files: list[Path] = []
        if target.is_file():
            if target.suffix == ".py":
                py_files = [target]
            else:
                return UseCaseResult(
                    success=False,
                    summary="",
                    error=f"File is not a Python source file: {target}",
                )
        else:
            py_files = sorted(target.rglob("*.py"))[:_MAX_FILES]

        if not py_files:
            return UseCaseResult(
                success=False,
                summary="",
                error=f"No Python (.py) files found under: {target}",
            )

        # ── Build code context ────────────────────────────────────────
        context_parts: list[str] = []
        total_chars = 0
        skipped: list[str] = []
        for py_file in py_files:
            try:
                size = py_file.stat().st_size
                if size > _MAX_FILE_BYTES:
                    skipped.append(f"{py_file.name} (too large: {size // 1024} KB)")
                    continue
                code = py_file.read_text(encoding="utf-8", errors="replace")
                snippet = f"### {py_file.name}\n```python\n{code}\n```\n"
                if total_chars + len(snippet) > _MAX_CONTEXT_CHARS:
                    skipped.append(f"{py_file.name} (context limit reached)")
                    break
                context_parts.append(snippet)
                total_chars += len(snippet)
            except OSError as exc:
                skipped.append(f"{py_file.name} (read error: {exc})")

        if not context_parts:
            return UseCaseResult(
                success=False,
                summary="",
                error="Could not read any source files. Check file permissions.",
            )

        code_context = "\n".join(context_parts)
        if focus.lower() != "all":
            code_context = (
                f"[Review focus areas: {focus}]\n\n" + code_context
            )

        # ── Run AI review ─────────────────────────────────────────────
        logger.info(
            "CodeReviewer: analysing %d file(s) (%d chars)...",
            len(context_parts), total_chars,
        )
        try:
            review = kernel.ai_adapter.chat(
                messages=[{"role": "user", "content": _REVIEW_PROMPT.format(
                    code_context=code_context,
                )}]
            )
        except Exception as exc:
            logger.error("CodeReviewer: AI call failed: %s", exc)
            return UseCaseResult(success=False, summary="", error=str(exc))

        # ── Write output ──────────────────────────────────────────────
        if target.is_file():
            out_path = target.parent / "code_review.md"
        else:
            out_path = target / "code_review.md"

        header = (
            f"# Code Review — {target.name}\n\n"
            f"**Files analysed:** {len(context_parts)}  |  "
            f"**Focus:** {focus}  |  "
            f"**Source:** `{target}`\n\n"
        )
        if skipped:
            header += f"**Skipped:** {', '.join(skipped)}\n\n---\n\n"
        full_report = header + review

        try:
            out_path.write_text(full_report, encoding="utf-8")
        except OSError as exc:
            logger.error("CodeReviewer: could not write report: %s", exc)
            return UseCaseResult(success=False, summary="", error=str(exc))

        summary = (
            f"Code review complete for '{target.name}'.\n"
            f"  • Files analysed : {len(context_parts)}\n"
            f"  • Report written : {out_path}"
        )
        if skipped:
            summary += f"\n  • Skipped        : {len(skipped)} file(s)"

        return UseCaseResult(
            success=True,
            summary=summary,
            outputs={
                "files_analysed": len(context_parts),
                "focus": focus,
                "report_path": str(out_path),
                "skipped": skipped,
            },
            output_files=[("code_review.md", str(out_path))],
        )
