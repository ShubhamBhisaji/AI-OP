"""Factory and container helpers for modular integration wiring."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from integrations.infobip_client import InfobipClient
from integrations.meta_api_client import MetaAPIClient
from integrations.payu_client import PayUClient
from integrations.supabase_client import SupabaseClient
from integrations.vercel_client import VercelClient


@dataclass(slots=True)
class IntegrationClients:
    supabase: SupabaseClient
    infobip: InfobipClient
    payu: PayUClient
    meta: MetaAPIClient
    vercel: VercelClient


class IntegrationFactory:
    """
    Build integration clients with optional runtime overrides.

    This makes integrations replaceable (for tests, mocks, or provider swaps)
    without changing consumer code.
    """

    def __init__(self, overrides: Mapping[str, Any] | None = None) -> None:
        self._overrides = dict(overrides or {})

    def create(self) -> IntegrationClients:
        return IntegrationClients(
            supabase=self._resolve("supabase", SupabaseClient),
            infobip=self._resolve("infobip", InfobipClient),
            payu=self._resolve("payu", PayUClient),
            meta=self._resolve("meta", MetaAPIClient),
            vercel=self._resolve("vercel", VercelClient),
        )

    def _resolve(self, key: str, default_cls: Callable[[], Any]) -> Any:
        override = self._overrides.get(key)
        if override is None:
            return default_cls()

        if callable(override):
            return override()

        return override
