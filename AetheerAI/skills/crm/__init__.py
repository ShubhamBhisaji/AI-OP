"""skills.crm — Pluggable CRM skill pack.

Loaded automatically by AgentFactory.load_skills() when "crm"
appears in an AgentSpec.skills list.
"""

from __future__ import annotations

SKILLS: list[str] = [
    # Foundation
    "contact_management",
    "lead_qualification",
    "deal_tracking",
    "activity_logging",
    "customer_segmentation",
    # Intermediate
    "pipeline_management",
    "follow_up_scheduling",
    "email_sequence_automation",
    "customer_lifecycle_mapping",
    "churn_prediction",
    "sentiment_tagging",
    # Advanced
    "revenue_attribution",
    "account_based_marketing",
    "sales_forecasting",
    "multi_touch_attribution",
    "customer_health_scoring",
    "win_loss_analysis",
]

TOOLS: list[str] = [
    "http_client",
    "email_tool",
    "csv_tool",
]

INTEGRATION_HINTS: list[str] = ["crm", "email", "api"]


def load() -> dict:
    return {
        "domain": "crm",
        "skills": SKILLS,
        "tools": TOOLS,
        "integration_hints": INTEGRATION_HINTS,
    }
