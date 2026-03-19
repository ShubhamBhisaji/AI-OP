"""skills.communication — Pluggable communication skill pack.

Loaded automatically by AgentFactory.load_skills() when "communication"
appears in an AgentSpec.skills list.
"""

from __future__ import annotations

# Skills exposed by this domain pack
SKILLS: list[str] = [
    # Foundation
    "active_listening",
    "clear_writing",
    "tone_adaptation",
    "audience_awareness",
    # Intermediate
    "persuasive_messaging",
    "conflict_resolution",
    "cross_cultural_communication",
    "feedback_delivery",
    "meeting_facilitation",
    # Advanced
    "executive_communication",
    "crisis_communication",
    "storytelling",
    "negotiation",
    "public_speaking_coaching",
]

# Tools that complement this skill pack
TOOLS: list[str] = [
    "email_tool",
    "slack_discord_tool",
]

# Integration hints — integrations that pair naturally with this domain
INTEGRATION_HINTS: list[str] = ["email", "slack"]


def load() -> dict:
    """Return the full skill pack descriptor."""
    return {
        "domain": "communication",
        "skills": SKILLS,
        "tools": TOOLS,
        "integration_hints": INTEGRATION_HINTS,
    }
