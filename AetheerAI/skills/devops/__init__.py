"""skills.devops — Pluggable DevOps skill pack.

Loaded automatically by AgentFactory.load_skills() when "devops"
appears in an AgentSpec.skills list.
"""

from __future__ import annotations

SKILLS: list[str] = [
    # Foundation
    "version_control",
    "ci_basics",
    "containerisation",
    "infrastructure_as_code",
    "log_analysis",
    # Intermediate
    "ci_cd_pipeline_design",
    "kubernetes_operations",
    "monitoring_and_alerting",
    "secret_management",
    "blue_green_deployment",
    "rollback_strategy",
    # Advanced
    "site_reliability_engineering",
    "chaos_engineering",
    "cost_optimisation",
    "multi_cloud_architecture",
    "zero_downtime_migration",
    "platform_engineering",
    "security_hardening",
]

TOOLS: list[str] = [
    "terminal_tool",
    "github_tool",
    "kubernetes_tool",
    "aws_gcp_tool",
    "code_runner",
]

INTEGRATION_HINTS: list[str] = ["devops", "api"]


def load() -> dict:
    return {
        "domain": "devops",
        "skills": SKILLS,
        "tools": TOOLS,
        "integration_hints": INTEGRATION_HINTS,
    }
