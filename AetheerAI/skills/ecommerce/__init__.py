"""skills.ecommerce — Pluggable e-commerce skill pack.

Loaded automatically by AgentFactory.load_skills() when "ecommerce"
appears in an AgentSpec.skills list.
"""

from __future__ import annotations

SKILLS: list[str] = [
    # Foundation
    "product_catalogue_management",
    "order_processing",
    "inventory_tracking",
    "customer_lookup",
    "pricing_rules",
    # Intermediate
    "cart_abandonment_recovery",
    "upsell_recommendation",
    "discount_and_promotion_logic",
    "return_and_refund_handling",
    "shipping_estimation",
    "payment_gateway_integration",
    # Advanced
    "personalisation_engine",
    "demand_forecasting",
    "marketplace_integration",
    "conversion_rate_optimisation",
    "loyalty_programme_management",
    "fraud_detection",
]

TOOLS: list[str] = [
    "http_client",
    "csv_tool",
    "json_tool",
    "web_search",
]

INTEGRATION_HINTS: list[str] = ["ecommerce", "website", "api"]


def load() -> dict:
    return {
        "domain": "ecommerce",
        "skills": SKILLS,
        "tools": TOOLS,
        "integration_hints": INTEGRATION_HINTS,
    }
