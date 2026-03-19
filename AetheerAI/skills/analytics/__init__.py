"""skills.analytics — Pluggable analytics & data skill pack.

Loaded automatically by AgentFactory.load_skills() when "analytics"
appears in an AgentSpec.skills list.
"""

from __future__ import annotations

SKILLS: list[str] = [
    # Foundation
    "data_cleaning",
    "exploratory_analysis",
    "sql",
    "visualization",
    "kpi_tracking",
    # Intermediate
    "statistical_modeling",
    "feature_engineering",
    "etl_pipeline",
    "data_validation",
    "dashboarding",
    "cohort_analysis",
    # Advanced
    "machine_learning",
    "predictive_modeling",
    "real_time_analytics",
    "mlops",
    "causal_inference",
    "anomaly_detection",
    "ab_testing_analysis",
]

TOOLS: list[str] = [
    "csv_tool",
    "analytics_tool",
    "sql_db_tool",
    "code_runner",
]

INTEGRATION_HINTS: list[str] = ["database", "analytics"]


def load() -> dict:
    return {
        "domain": "analytics",
        "skills": SKILLS,
        "tools": TOOLS,
        "integration_hints": INTEGRATION_HINTS,
    }
