"""Environment-driven settings for Infobip integration."""
from __future__ import annotations

from dataclasses import dataclass

from .base_config import env_int, env_optional, env_required


@dataclass(slots=True, frozen=True)
class InfobipConfig:
    base_url: str
    api_key: str
    whatsapp_sender: str
    email_sender: str
    timeout_seconds: int

    @classmethod
    def from_env(cls) -> "InfobipConfig":
        return cls(
            base_url=env_required("INFOBIP_BASE_URL"),
            api_key=env_required("INFOBIP_API_KEY"),
            whatsapp_sender=env_optional("INFOBIP_WHATSAPP_SENDER"),
            email_sender=env_optional("INFOBIP_EMAIL_SENDER"),
            timeout_seconds=env_int("INFOBIP_TIMEOUT_SECONDS", 20),
        )
