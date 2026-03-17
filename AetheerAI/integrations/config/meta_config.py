"""Environment-driven settings for Meta Graph API integration."""
from __future__ import annotations

from dataclasses import dataclass

from .base_config import env_int, env_optional, env_required


@dataclass(slots=True, frozen=True)
class MetaConfig:
    graph_base_url: str
    access_token: str
    app_id: str
    app_secret: str
    verify_token: str
    default_page_id: str
    default_instagram_business_id: str
    timeout_seconds: int

    @classmethod
    def from_env(cls) -> "MetaConfig":
        return cls(
            graph_base_url=env_optional(
                "META_GRAPH_BASE_URL", "https://graph.facebook.com/v20.0"
            ),
            access_token=env_required("META_ACCESS_TOKEN"),
            app_id=env_optional("META_APP_ID"),
            app_secret=env_optional("META_APP_SECRET"),
            verify_token=env_optional("META_WEBHOOK_VERIFY_TOKEN"),
            default_page_id=env_optional("META_DEFAULT_PAGE_ID"),
            default_instagram_business_id=env_optional(
                "META_DEFAULT_INSTAGRAM_BUSINESS_ID"
            ),
            timeout_seconds=env_int("META_TIMEOUT_SECONDS", 20),
        )
