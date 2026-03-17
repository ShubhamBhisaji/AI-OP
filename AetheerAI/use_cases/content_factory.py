"""
use_cases/content_factory.py — ContentFactory Use Case Pack.

Input  : brand name, product description, target audience
Output : 4 files written to projects/<brand_slug>/content/
           - blog_post.md          (1 000–1 200 word article with SEO headings)
           - social_posts.md       (5 platform-specific posts: LinkedIn, X, Instagram, Facebook, TikTok)
           - email_newsletter.md   (subject line + full HTML-ready email body)
           - seo_keywords.md       (primary + secondary keyword list + meta description)

Agent pipeline
--------------
  1. Researcher   — gathers industry context, trending topics, keyword opportunities
  2. Marketer     — drafts all four content pieces using research as context
  3. Synthesiser  — (CEO's final pass) assembles deliverables into the output folder
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from use_cases.base import InputField, UseCase, UseCaseResult

logger = logging.getLogger(__name__)

# ── Prompts ───────────────────────────────────────────────────────────────────

_RESEARCH_PROMPT = """\
You are a senior market researcher.

Brand      : {brand}
Product    : {product}
Audience   : {audience}

1. Summarise 3–5 key industry trends relevant to this product (2–3 sentences each).
2. Identify 8 high-value SEO keywords (mix of short-tail and long-tail) a buyer would search for.
3. List 3 compelling pain points the target audience has that this product solves.

Be factual and concise. Output plain text with clear headings.
"""

_BLOG_PROMPT = """\
You are a professional content writer.

Brand      : {brand}
Product    : {product}
Audience   : {audience}

Research context:
{research}

Write a 1 000–1 200 word blog post that:
- Has an SEO-optimised title (include primary keyword)
- Opens with a compelling hook
- Has 4–5 H2 sections using keywords naturally
- Includes concrete benefits and a real-world use case
- Ends with a clear call-to-action for {brand}

Output Markdown only — no commentary.
"""

_SOCIAL_PROMPT = """\
You are a social media strategist.

Brand      : {brand}
Product    : {product}
Audience   : {audience}

Write exactly 5 platform-specific social media posts promoting this product:

1. LinkedIn   (professional tone, 150–200 words, include 3 hashtags)
2. X/Twitter  (punchy, ≤280 chars, 2 hashtags)
3. Instagram  (visual-first caption, 80–120 words, 5–7 hashtags)
4. Facebook   (conversational, 100–150 words, ask a question to drive comments)
5. TikTok     (script for a 30–45 second video with text-on-screen cues)

Separate each post with a clear heading like "## LinkedIn".
Output Markdown only.
"""

_EMAIL_PROMPT = """\
You are an email marketing specialist.

Brand      : {brand}
Product    : {product}
Audience   : {audience}

Write a marketing email newsletter:
- Subject line (≤60 chars, A/B test variant as alternative)
- Preview text (≤90 chars)
- Full email body (400–500 words)
  * Greeting personalisation placeholder
  * Problem → Solution story arc
  * 3 bullet-point features/benefits
  * Single clear CTA button (text + link placeholder)
  * P.S. line for urgency

Output Markdown only. Use "## Subject:", "## Preview:", "## Body:" headings.
"""

_SEO_PROMPT = """\
You are an SEO strategist.

Brand      : {brand}
Product    : {product}
Audience   : {audience}

Research context:
{research}

Produce:
1. Primary keyword (1 phrase, highest search intent)
2. 10 secondary keywords (include question-format & long-tail variants)
3. Meta description (≤155 chars, include primary keyword, clear value prop)
4. Open Graph title (≤60 chars)
5. 3 topic cluster ideas for supporting blog posts

Output Markdown only with clear headings.
"""


class ContentFactory(UseCase):
    """
    Turn a product brief into a full marketing content kit.

    One command → 4 ready-to-publish content files.
    """

    @property
    def name(self) -> str:
        return "content_factory"

    @property
    def title(self) -> str:
        return "Content Factory"

    @property
    def description(self) -> str:
        return (
            "Turn a product brief into a full marketing kit: "
            "blog post, social posts, email newsletter, and SEO keywords."
        )

    @property
    def inputs(self) -> list[InputField]:
        return [
            InputField(
                name="brand",
                description="Your brand or company name.",
                required=True,
                example="TaskFlow",
            ),
            InputField(
                name="product",
                description="A one-to-three sentence description of your product or service.",
                required=True,
                example="TaskFlow is an AI-powered project management tool that eliminates status meetings.",
            ),
            InputField(
                name="audience",
                description="Your target audience (who buys / uses this product).",
                required=True,
                example="Remote engineering teams at 20–200 person SaaS companies",
            ),
            InputField(
                name="output_dir",
                description="Where to write the output files. Defaults to projects/<brand>/content/.",
                required=False,
                default=None,
                example="projects/taskflow/content",
            ),
        ]

    # ------------------------------------------------------------------

    def run(self, inputs: dict[str, Any], kernel) -> UseCaseResult:
        brand: str = inputs["brand"].strip()
        product: str = inputs["product"].strip()
        audience: str = inputs["audience"].strip()
        brand_slug = re.sub(r"[^a-z0-9_-]", "_", brand.lower())

        # Resolve output directory
        raw_out = inputs.get("output_dir") or ""
        if raw_out:
            out_dir = Path(raw_out)
        else:
            root = Path(__file__).resolve().parents[2]  # workspace root
            out_dir = root / "projects" / brand_slug / "content"
        out_dir.mkdir(parents=True, exist_ok=True)

        ai = kernel.ai_adapter

        def _chat(prompt: str) -> str:
            try:
                return ai.chat(messages=[{"role": "user", "content": prompt}])
            except Exception as exc:
                logger.error("ContentFactory: AI call failed: %s", exc)
                return f"[AI call failed: {exc}]"

        # ── Step 1: Research ──────────────────────────────────────────
        logger.info("ContentFactory: running research pass...")
        research = _chat(_RESEARCH_PROMPT.format(
            brand=brand, product=product, audience=audience))

        # ── Step 2: Generate all four content pieces ──────────────────
        logger.info("ContentFactory: generating blog post...")
        blog = _chat(_BLOG_PROMPT.format(
            brand=brand, product=product, audience=audience, research=research[:3000]))

        logger.info("ContentFactory: generating social posts...")
        social = _chat(_SOCIAL_PROMPT.format(
            brand=brand, product=product, audience=audience))

        logger.info("ContentFactory: generating email newsletter...")
        email = _chat(_EMAIL_PROMPT.format(
            brand=brand, product=product, audience=audience))

        logger.info("ContentFactory: generating SEO keywords...")
        seo = _chat(_SEO_PROMPT.format(
            brand=brand, product=product, audience=audience, research=research[:3000]))

        # ── Step 3: Write deliverables ────────────────────────────────
        files: list[tuple[str, str]] = []
        deliverables = {
            "blog_post.md": blog,
            "social_posts.md": social,
            "email_newsletter.md": email,
            "seo_keywords.md": seo,
        }
        for filename, content in deliverables.items():
            dest = out_dir / filename
            try:
                dest.write_text(content, encoding="utf-8")
                files.append((filename, str(dest)))
                logger.info("ContentFactory: wrote %s", dest)
            except OSError as exc:
                logger.error("ContentFactory: could not write %s: %s", dest, exc)

        summary = (
            f"Content kit for '{brand}' written to {out_dir}/\n"
            f"  • blog_post.md        — 1 000–1 200 word article\n"
            f"  • social_posts.md     — 5 platform-specific posts\n"
            f"  • email_newsletter.md — subject + full email body\n"
            f"  • seo_keywords.md     — keywords + meta description"
        )
        return UseCaseResult(
            success=len(files) > 0,
            summary=summary,
            outputs={
                "brand": brand,
                "output_dir": str(out_dir),
                "files_written": len(files),
            },
            output_files=files,
            error=None if files else "All file writes failed — check permissions.",
        )
