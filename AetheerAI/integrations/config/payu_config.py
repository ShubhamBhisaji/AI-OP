"""Environment-driven settings for PayU Money integration."""
from __future__ import annotations

from dataclasses import dataclass

from .base_config import env_int, env_optional, env_required


@dataclass(slots=True, frozen=True)
class PayUConfig:
    merchant_key: str
    merchant_salt: str
    base_url: str
    payment_path: str
    postservice_path: str
    success_url: str
    failure_url: str
    timeout_seconds: int

    @classmethod
    def from_env(cls) -> "PayUConfig":
        return cls(
            merchant_key=env_required("PAYU_MERCHANT_KEY"),
            merchant_salt=env_required("PAYU_MERCHANT_SALT"),
            base_url=env_optional("PAYU_BASE_URL", "https://secure.payu.in"),
            payment_path=env_optional("PAYU_PAYMENT_PATH", "/_payment"),
            postservice_path=env_optional(
                "PAYU_POSTSERVICE_PATH",
                "/merchant/postservice?form=2",
            ),
            success_url=env_required("PAYU_SUCCESS_URL"),
            failure_url=env_required("PAYU_FAILURE_URL"),
            timeout_seconds=env_int("PAYU_TIMEOUT_SECONDS", 20),
        )
