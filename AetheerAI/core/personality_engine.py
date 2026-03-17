"""
Personality Engine — Human-AI Team Personality Matching

Research in early 2026 showed that AI-human teams perform significantly
better when communication styles align.  The Personality Engine profiles
the human user from their conversation patterns and tunes each sub-agent's
response style to match — executives get concise bullet dashboards, creatives
get collaborative brainstorm energy, engineers get raw technical depth.

Architecture
------------
  PersonalityProfile  — the 5 user archetypes
  CommunicationStyle  — concrete style parameters for an archetype
  StyledResponse      — a transformed response with audit trail
  PersonalityEngine   — main facade

Usage
-----
    pe = PersonalityEngine(ai_adapter)

    # Auto-detect the user's profile from recent messages
    profile = pe.detect_user_profile(["Show me the P&L", "What's the EBITDA?"])
    # → PersonalityProfile.EXECUTIVE

    # Assign a style to an agent
    pe.set_agent_style("ReportingAgent", profile)

    # Style an agent's raw response
    styled = pe.style_response("ReportingAgent", raw_response, context="Q3 report")
    print(styled.styled)   # ← concise, data-heavy executive version
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Enums & data structures
# ═══════════════════════════════════════════════════════════════════════════


class PersonalityProfile(str, Enum):
    EXECUTIVE    = "EXECUTIVE"     # C-suite: numbers, brevity, impact
    CREATIVE     = "CREATIVE"      # Designers/marketers: ideas, warmth, possibility
    TECHNICAL    = "TECHNICAL"     # Engineers: precision, depth, syntax
    ANALYTICAL   = "ANALYTICAL"    # Analysts/researchers: data, citations, caveats
    COLLABORATIVE= "COLLABORATIVE" # PMs/ops: consensus, bullet lists, next steps


@dataclass
class CommunicationStyle:
    profile: PersonalityProfile
    tone: str                    # e.g. "authoritative", "energetic", "precise"
    verbosity: str               # "ultra-brief" | "concise" | "detailed" | "exhaustive"
    format_preference: str       # "bullet-metrics" | "narrative" | "code-first" | "table" | "checklist"
    use_emojis: bool
    use_technical_jargon: bool
    opener_style: str            # e.g. "Bottom line: " | "Here's the idea: "
    max_response_sentences: int  # 0 = no limit


STYLE_CATALOG: dict[PersonalityProfile, CommunicationStyle] = {
    PersonalityProfile.EXECUTIVE: CommunicationStyle(
        profile         = PersonalityProfile.EXECUTIVE,
        tone            = "authoritative",
        verbosity       = "ultra-brief",
        format_preference = "bullet-metrics",
        use_emojis      = False,
        use_technical_jargon = False,
        opener_style    = "Bottom line: ",
        max_response_sentences = 4,
    ),
    PersonalityProfile.CREATIVE: CommunicationStyle(
        profile         = PersonalityProfile.CREATIVE,
        tone            = "energetic and warm",
        verbosity       = "detailed",
        format_preference = "narrative",
        use_emojis      = True,
        use_technical_jargon = False,
        opener_style    = "Here's an idea — ",
        max_response_sentences = 0,
    ),
    PersonalityProfile.TECHNICAL: CommunicationStyle(
        profile         = PersonalityProfile.TECHNICAL,
        tone            = "precise and direct",
        verbosity       = "exhaustive",
        format_preference = "code-first",
        use_emojis      = False,
        use_technical_jargon = True,
        opener_style    = "",
        max_response_sentences = 0,
    ),
    PersonalityProfile.ANALYTICAL: CommunicationStyle(
        profile         = PersonalityProfile.ANALYTICAL,
        tone            = "measured and evidence-based",
        verbosity       = "detailed",
        format_preference = "table",
        use_emojis      = False,
        use_technical_jargon = True,
        opener_style    = "The data shows: ",
        max_response_sentences = 0,
    ),
    PersonalityProfile.COLLABORATIVE: CommunicationStyle(
        profile         = PersonalityProfile.COLLABORATIVE,
        tone            = "inclusive and action-oriented",
        verbosity       = "concise",
        format_preference = "checklist",
        use_emojis      = True,
        use_technical_jargon = False,
        opener_style    = "Here's what we can do: ",
        max_response_sentences = 0,
    ),
}


@dataclass
class StyledResponse:
    agent_name: str
    profile_applied: PersonalityProfile
    original: str
    styled: str
    transformations: list[str]    # human-readable list of changes made
    processing_ms: float = 0.0


@dataclass
class ProfileDetectionResult:
    profile: PersonalityProfile
    confidence: float             # 0–1
    signal_words: list[str]       # words that triggered this profile
    reasoning: str


# ═══════════════════════════════════════════════════════════════════════════
# Personality Engine
# ═══════════════════════════════════════════════════════════════════════════


class PersonalityEngine:
    """
    AI-powered communication style tuner for human-AI teams.

    Parameters
    ----------
    ai_adapter : AIAdapter  — used for AI-powered profile detection and styling.
    """

    def __init__(self, ai_adapter):
        self.ai_adapter = ai_adapter
        self._agent_styles:   dict[str, PersonalityProfile]  = {}
        self._user_profile:   PersonalityProfile | None       = None
        self._detection_log:  list[ProfileDetectionResult]   = []
        self._styled_log:     list[StyledResponse]            = []

    # ──────────────────────────────────────────────────────────────────
    # Profile detection
    # ──────────────────────────────────────────────────────────────────

    _PROFILE_SIGNALS: dict[PersonalityProfile, list[str]] = {
        PersonalityProfile.EXECUTIVE:     ["ROI", "P&L", "EBITDA", "bottom line", "headline", "executive", "KPI", "revenue", "strategy", "board"],
        PersonalityProfile.CREATIVE:      ["brainstorm", "idea", "creative", "design", "brand", "feel", "vibe", "story", "inspire", "imagine"],
        PersonalityProfile.TECHNICAL:     ["function", "code", "API", "debug", "deploy", "stack", "implementation", "class", "algorithm", "architecture"],
        PersonalityProfile.ANALYTICAL:    ["data", "statistics", "analysis", "hypothesis", "correlation", "dataset", "metrics", "benchmark", "evidence", "regression"],
        PersonalityProfile.COLLABORATIVE: ["team", "process", "workflow", "checklist", "next steps", "stakeholder", "align", "sync", "meeting", "together"],
    }

    def detect_user_profile(
        self,
        conversation_history: list[str],
        use_ai: bool = False,
    ) -> ProfileDetectionResult:
        """
        Detect the user's personality profile from a list of recent messages.

        Parameters
        ----------
        conversation_history : List of user message strings.
        use_ai               : If True, uses AI for richer analysis (costs tokens).
        """
        combined = " ".join(conversation_history).lower()

        if use_ai and conversation_history:
            return self._detect_via_ai(combined, conversation_history)

        # Heuristic keyword scoring
        scores: dict[PersonalityProfile, float] = {p: 0.0 for p in PersonalityProfile}
        signal_words: dict[PersonalityProfile, list[str]] = {p: [] for p in PersonalityProfile}

        for profile, keywords in self._PROFILE_SIGNALS.items():
            for kw in keywords:
                if kw.lower() in combined:
                    scores[profile] += 1.0
                    signal_words[profile].append(kw)

        # Boost based on message length patterns
        avg_len = sum(len(m.split()) for m in conversation_history) / max(len(conversation_history), 1)
        if avg_len < 10:
            scores[PersonalityProfile.EXECUTIVE] += 0.5
        elif avg_len > 40:
            scores[PersonalityProfile.ANALYTICAL] += 0.5

        total = sum(scores.values()) or 1.0
        best  = max(scores, key=lambda p: scores[p])
        conf  = scores[best] / total if total > 0 else 0.2

        result = ProfileDetectionResult(
            profile=best,
            confidence=round(conf, 2),
            signal_words=signal_words[best],
            reasoning=(
                f"Detected {best.value} from {len(conversation_history)} messages. "
                f"Key signals: {', '.join(signal_words[best][:4]) or 'general pattern'}."
            ),
        )
        self._detection_log.append(result)
        self._user_profile = best
        return result

    def _detect_via_ai(self, combined: str, history: list[str]) -> ProfileDetectionResult:
        sample = combined[:3000]
        prompt = f"""Analyse these user messages and classify the user's communication profile.

Messages (sample):
---
{sample}
---

Profiles to choose from:
- EXECUTIVE: Numbers-driven, wants brevity, talks about strategy/KPIs/revenue
- CREATIVE: Idea-driven, collaborative, uses words like "imagine", "vibe", "story"
- TECHNICAL: Code/architecture focused, values precision and depth
- ANALYTICAL: Data-driven, values evidence, citations, statistical language
- COLLABORATIVE: Process-focused, teamwork, next steps, stakeholder alignment

Return ONLY valid JSON:
{{
  "profile": "EXECUTIVE|CREATIVE|TECHNICAL|ANALYTICAL|COLLABORATIVE",
  "confidence": 0.0-1.0,
  "signal_words": ["<word1>", "<word2>"],
  "reasoning": "<one sentence>"
}}"""

        raw = self.ai_adapter.chat([
            {"role": "system", "content": "You are a communication style analyst. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ])
        data = self._parse_json(raw)
        try:
            profile = PersonalityProfile(data.get("profile", "COLLABORATIVE"))
        except ValueError:
            profile = PersonalityProfile.COLLABORATIVE

        result = ProfileDetectionResult(
            profile=profile,
            confidence=float(data.get("confidence", 0.5)),
            signal_words=data.get("signal_words", []),
            reasoning=data.get("reasoning", "AI-detected profile."),
        )
        self._detection_log.append(result)
        self._user_profile = profile
        return result

    # ──────────────────────────────────────────────────────────────────
    # Style assignment
    # ──────────────────────────────────────────────────────────────────

    def set_agent_style(
        self,
        agent_name: str,
        profile: PersonalityProfile | str,
    ) -> None:
        """Assign a communication style profile to an agent."""
        if isinstance(profile, str):
            profile = PersonalityProfile(profile.upper())
        self._agent_styles[agent_name] = profile
        logger.info("PersonalityEngine: %s → %s style", agent_name, profile.value)

    def get_style(self, agent_name: str) -> CommunicationStyle:
        """Return the CommunicationStyle for an agent (default: COLLABORATIVE)."""
        profile = self._agent_styles.get(agent_name, PersonalityProfile.COLLABORATIVE)
        return STYLE_CATALOG[profile]

    # ──────────────────────────────────────────────────────────────────
    # Response styling
    # ──────────────────────────────────────────────────────────────────

    def style_response(
        self,
        agent_name: str,
        response: str,
        context: str = "",
        force_profile: PersonalityProfile | str | None = None,
    ) -> StyledResponse:
        """
        Rewrite an agent's raw response in the assigned communication style.

        Parameters
        ----------
        agent_name     : The agent whose style profile should be applied.
        response       : The raw AI response to be styled.
        context        : Brief context description (helps the AI style accurately).
        force_profile  : Override the agent's default profile for this call only.
        """
        t0 = time.time()

        if force_profile:
            if isinstance(force_profile, str):
                force_profile = PersonalityProfile(force_profile.upper())
            profile = force_profile
        else:
            profile = self._agent_styles.get(agent_name, PersonalityProfile.COLLABORATIVE)

        style = STYLE_CATALOG[profile]
        transformations: list[str] = []

        # Build style-specific prompt
        constraints = []
        if style.max_response_sentences > 0:
            constraints.append(f"Use at most {style.max_response_sentences} sentences.")
        if style.verbosity == "ultra-brief":
            constraints.append("Be extremely concise — executives scan, not read.")
        if style.use_emojis:
            constraints.append("Use 1-2 relevant emojis to add warmth.")
        if not style.use_emojis:
            constraints.append("Do NOT use emojis — keep it professional.")
        if style.use_technical_jargon:
            constraints.append("Use precise technical language; do not oversimplify.")
        if not style.use_technical_jargon:
            constraints.append("Avoid technical jargon; use plain business language.")
        if style.format_preference == "bullet-metrics":
            constraints.append("Format as short bullet points with numbers/percentages where possible.")
            transformations.append("Converted to metric bullet points")
        elif style.format_preference == "code-first":
            constraints.append("Lead with code or technical commands when relevant.")
            transformations.append("Prioritised code/technical content")
        elif style.format_preference == "table":
            constraints.append("Use tables where data allows.")
            transformations.append("Structured into data table")
        elif style.format_preference == "checklist":
            constraints.append("Format as a checkbox-style action list.")
            transformations.append("Converted to checklist")
        elif style.format_preference == "narrative":
            constraints.append("Write as flowing narrative — tell a story with the data.")
            transformations.append("Converted to narrative style")

        opener = f'Start with "{style.opener_style}"' if style.opener_style else ""

        prompt = f"""Rewrite the following AI response for a {profile.value} user.

Tone: {style.tone}
{opener}
Constraints:
{chr(10).join(f"- {c}" for c in constraints)}

Context: {context or "general"}

Original response:
---
{response}
---

Rewrite it now, following the constraints above exactly. Return only the rewritten response — no meta-commentary."""

        try:
            styled_text = self.ai_adapter.chat([
                {
                    "role": "system",
                    "content": (
                        f"You are a communication style adapter. Rewrite responses for {profile.value} users. "
                        "Return only the rewritten content."
                    ),
                },
                {"role": "user", "content": prompt},
            ])
            transformations.append(f"Style applied: {profile.value}")
        except Exception as exc:
            logger.warning("PersonalityEngine: styling failed: %s", exc)
            styled_text = response
            transformations.append("Styling failed — returned original")

        result = StyledResponse(
            agent_name=agent_name,
            profile_applied=profile,
            original=response,
            styled=styled_text,
            transformations=transformations,
            processing_ms=(time.time() - t0) * 1000,
        )
        self._styled_log.append(result)
        return result

    # ──────────────────────────────────────────────────────────────────
    # Read-only views
    # ──────────────────────────────────────────────────────────────────

    def available_profiles(self) -> list[str]:
        return [p.value for p in PersonalityProfile]

    def profile_descriptions(self) -> list[dict]:
        return [
            {
                "profile": p.value,
                "tone": s.tone,
                "verbosity": s.verbosity,
                "format": s.format_preference,
                "emojis": s.use_emojis,
                "jargon": s.use_technical_jargon,
                "opener": s.opener_style,
            }
            for p, s in STYLE_CATALOG.items()
        ]

    def agent_styles(self) -> dict[str, str]:
        return {name: p.value for name, p in self._agent_styles.items()}

    def current_user_profile(self) -> str | None:
        return self._user_profile.value if self._user_profile else None

    def detection_history(self) -> list[dict]:
        return [
            {
                "profile": r.profile.value,
                "confidence": r.confidence,
                "signal_words": r.signal_words,
                "reasoning": r.reasoning,
            }
            for r in self._detection_log
        ]

    def styling_stats(self) -> dict:
        if not self._styled_log:
            return {"total": 0}
        by_profile: dict[str, int] = {}
        for s in self._styled_log:
            key = s.profile_applied.value
            by_profile[key] = by_profile.get(key, 0) + 1
        return {
            "total": len(self._styled_log),
            "by_profile": by_profile,
            "avg_processing_ms": sum(s.processing_ms for s in self._styled_log) / len(self._styled_log),
        }

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(text: str) -> dict:
        for pattern in (r"```(?:json)?\s*([\s\S]+?)```", r"\{[\s\S]+\}"):
            m = re.search(pattern, text)
            if m:
                fragment = m.group(1) if "```" in pattern else m.group()
                try:
                    return json.loads(fragment)
                except json.JSONDecodeError:
                    pass
        return {}
