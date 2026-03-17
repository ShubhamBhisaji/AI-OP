"""
use_cases/market_intel.py — MarketIntel Use Case Pack.

Input  : topic, competitors (comma-separated list), geography (optional)
Output : 1 file written to projects/market_intel/<slug>/brief.md
           Sections:
             - Market Snapshot      (size, growth, key drivers)
             - Competitive Landscape (table: competitor × positioning + strengths + weaknesses)
             - Gaps & Opportunities  (3–5 whitespace opportunities your brand can exploit)
             - Recommended Positioning Statement (1–2 sentences)
             - Immediate Next Actions (3 prioritised action items)

Agent pipeline
--------------
  1. Researcher — builds per-competitor profiles and market context
  2. Analyst    — synthesises into the strategic brief
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from use_cases.base import InputField, UseCase, UseCaseResult

logger = logging.getLogger(__name__)

# ── Prompts ───────────────────────────────────────────────────────────────────

_COMPETITOR_RESEARCH_PROMPT = """\
You are a senior market intelligence analyst.

Topic / Market    : {topic}
Competitors       : {competitors}
Geography         : {geography}

For EACH competitor listed, provide:
1. Core product/service (2–3 sentences)
2. Stated positioning / tagline
3. Key strengths (3 bullet points)
4. Key weaknesses / gaps (3 bullet points)
5. Estimated customer segments they target

Then provide:
- Market size estimate (TAM/SAM if available)
- Top 3 market trends driving growth or change
- Major regulatory or environmental factors (if relevant)

Be factual. Clearly mark any estimates as such. Output plain text with clear headings.
"""

_SYNTHESIS_PROMPT = """\
You are a strategy consultant writing a concise competitive intelligence brief.

Topic / Market : {topic}
Geography      : {geography}

Research gathered:
{research}

Write a structured Markdown competitive intelligence brief with EXACTLY these sections
(use ## headings):

## Market Snapshot
- Estimated market size and growth rate
- 3 key market drivers (bullet points)

## Competitive Landscape
Build a Markdown table with columns:
| Competitor | Core Positioning | Key Strengths | Key Weaknesses | Target Segment |

## Gaps & Opportunities
List 3–5 specific, actionable whitespace opportunities not well-served by current competitors.
Each as a bullet point with a 1-sentence rationale.

## Recommended Positioning Statement
Write 1–2 sentences that differentiate from the listed competitors.
(Placeholder: replace "YourBrand" with the actual brand name.)

## Immediate Next Actions
3 prioritised action items a product/marketing team should take in the next 30 days.
Format: ordered list.

---
Keep the tone professional and data-grounded. Base everything on the research above.
"""


class MarketIntel(UseCase):
    """
    One-command competitive intelligence brief for any market.

    Input a topic + list of competitors → receive a structured strategic brief.
    Ready to share with product, sales, and leadership teams.
    """

    @property
    def name(self) -> str:
        return "market_intel"

    @property
    def title(self) -> str:
        return "Market Intelligence"

    @property
    def description(self) -> str:
        return (
            "Generate a competitive intelligence brief: market snapshot, "
            "competitor comparison table, gaps & opportunities, and next actions."
        )

    @property
    def inputs(self) -> list[InputField]:
        return [
            InputField(
                name="topic",
                description="The market, product category, or technology to research.",
                required=True,
                example="AI-powered project management tools",
            ),
            InputField(
                name="competitors",
                description="Comma-separated list of competitor brand or product names.",
                required=True,
                example="Asana, Monday.com, ClickUp, Notion",
            ),
            InputField(
                name="geography",
                description="Target geography for the analysis (default: Global).",
                required=False,
                default="Global",
                example="North America",
            ),
            InputField(
                name="output_dir",
                description=(
                    "Where to write the brief. "
                    "Defaults to projects/market_intel/<topic_slug>/."
                ),
                required=False,
                default=None,
                example="projects/market_intel/pm-tools",
            ),
        ]

    # ------------------------------------------------------------------

    def run(self, inputs: dict[str, Any], kernel) -> UseCaseResult:
        topic: str = inputs["topic"].strip()
        competitors_raw: str = inputs["competitors"].strip()
        geography: str = (inputs.get("geography") or "Global").strip()

        # Parse and validate competitors list
        competitors: list[str] = [
            c.strip() for c in re.split(r"[,;]+", competitors_raw) if c.strip()
        ]
        if not competitors:
            return UseCaseResult(
                success=False,
                summary="",
                error="'competitors' must be a non-empty comma-separated list.",
            )

        # Resolve output path
        topic_slug = re.sub(r"[^a-z0-9_-]", "_", topic.lower())[:40]
        raw_out = inputs.get("output_dir") or ""
        if raw_out:
            out_dir = Path(raw_out)
        else:
            workspace_root = Path(__file__).resolve().parents[2]
            out_dir = workspace_root / "projects" / "market_intel" / topic_slug
        out_dir.mkdir(parents=True, exist_ok=True)

        ai = kernel.ai_adapter

        def _chat(prompt: str) -> str:
            try:
                return ai.chat(messages=[{"role": "user", "content": prompt}])
            except Exception as exc:
                logger.error("MarketIntel: AI call failed: %s", exc)
                return f"[AI call failed: {exc}]"

        competitors_str = ", ".join(competitors)

        # ── Step 1: Research each competitor + market context ─────────
        logger.info("MarketIntel: running competitor research pass...")
        research = _chat(_COMPETITOR_RESEARCH_PROMPT.format(
            topic=topic,
            competitors=competitors_str,
            geography=geography,
        ))

        # ── Step 2: Synthesise into strategic brief ───────────────────
        logger.info("MarketIntel: synthesising competitive intelligence brief...")
        brief_body = _chat(_SYNTHESIS_PROMPT.format(
            topic=topic,
            geography=geography,
            research=research[:6000],
        ))

        # ── Step 3: Write output ──────────────────────────────────────
        header = (
            f"# Competitive Intelligence Brief\n\n"
            f"**Topic:** {topic}  \n"
            f"**Competitors:** {competitors_str}  \n"
            f"**Geography:** {geography}  \n"
            f"**Generated:** {_now_str()}\n\n---\n\n"
        )
        full_brief = header + brief_body

        out_path = out_dir / "brief.md"
        try:
            out_path.write_text(full_brief, encoding="utf-8")
        except OSError as exc:
            logger.error("MarketIntel: could not write brief: %s", exc)
            return UseCaseResult(success=False, summary="", error=str(exc))

        summary = (
            f"Market intelligence brief for '{topic}' written to:\n"
            f"  {out_path}\n"
            f"  Competitors analysed : {len(competitors)}\n"
            f"  Geography            : {geography}"
        )
        return UseCaseResult(
            success=True,
            summary=summary,
            outputs={
                "topic": topic,
                "competitors": competitors,
                "geography": geography,
                "report_path": str(out_path),
            },
            output_files=[("brief.md", str(out_path))],
        )


def _now_str() -> str:
    """Return current date as YYYY-MM-DD string without importing datetime at module level."""
    import datetime
    return datetime.date.today().isoformat()
