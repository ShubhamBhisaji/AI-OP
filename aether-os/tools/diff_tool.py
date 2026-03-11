"""diff_tool — Compare two texts and show their differences."""
from __future__ import annotations
import difflib, logging

logger = logging.getLogger(__name__)


def diff_tool(text_a: str, text_b: str, mode: str = "unified") -> str:
    """
    Show the difference between two text strings.

    text_a : First (original) text.
    text_b : Second (modified) text.
    mode   : unified | summary | added | removed | ratio

    Modes:
        unified  : Standard unified diff with +/- lines and context.
        summary  : High-level stats (lines added, removed, unchanged).
        added    : Only the lines present in text_b but not text_a.
        removed  : Only the lines present in text_a but not text_b.
        ratio    : Similarity ratio (0.0 = completely different, 1.0 = identical).
    """
    if not isinstance(text_a, str):
        text_a = str(text_a)
    if not isinstance(text_b, str):
        text_b = str(text_b)

    mode = (mode or "unified").strip().lower()
    lines_a = text_a.splitlines(keepends=True)
    lines_b = text_b.splitlines(keepends=True)

    if mode == "unified":
        diff = list(difflib.unified_diff(lines_a, lines_b, fromfile="text_a", tofile="text_b", lineterm=""))
        if not diff:
            return "No differences — texts are identical."
        return "\n".join(diff[:500]) + ("\n\n[truncated]" if len(diff) > 500 else "")

    if mode == "summary":
        added = removed = unchanged = 0
        for line in difflib.ndiff(lines_a, lines_b):
            if line.startswith("+ "):   added += 1
            elif line.startswith("- "): removed += 1
            elif line.startswith("  "): unchanged += 1
        return (
            f"Lines added    : {added}\n"
            f"Lines removed  : {removed}\n"
            f"Lines unchanged: {unchanged}\n"
            f"Total in A     : {len(lines_a)}\n"
            f"Total in B     : {len(lines_b)}"
        )

    if mode == "added":
        added = [
            line[2:].rstrip("\n")
            for line in difflib.ndiff(lines_a, lines_b)
            if line.startswith("+ ")
        ]
        return "\n".join(added) if added else "(no lines were added)"

    if mode == "removed":
        removed = [
            line[2:].rstrip("\n")
            for line in difflib.ndiff(lines_a, lines_b)
            if line.startswith("- ")
        ]
        return "\n".join(removed) if removed else "(no lines were removed)"

    if mode == "ratio":
        ratio = difflib.SequenceMatcher(None, text_a, text_b).ratio()
        pct = ratio * 100
        desc = "identical" if ratio == 1.0 else ("very similar" if ratio > 0.8 else ("similar" if ratio > 0.5 else "very different"))
        return f"Similarity ratio: {ratio:.4f} ({pct:.1f}%) — {desc}"

    return f"Unknown mode '{mode}'. Use: unified, summary, added, removed, ratio."
