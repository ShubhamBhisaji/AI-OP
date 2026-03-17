"""Environment-driven settings for Supabase integration."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from .base_config import env_int, env_optional, env_required


@dataclass(slots=True, frozen=True)
class SupabaseConfig:
    url: str
    anon_key: str
    service_role_key: str
    schema: str
    timeout_seconds: int

    @classmethod
    def from_env(cls) -> "SupabaseConfig":
        return cls(
            url=env_required("SUPABASE_URL"),
            anon_key=env_required("SUPABASE_ANON_KEY"),
            service_role_key=env_optional("SUPABASE_SERVICE_ROLE_KEY"),
            schema=env_optional("SUPABASE_SCHEMA", "public"),
            timeout_seconds=env_int("SUPABASE_TIMEOUT_SECONDS", 20),
        )

    @property
    def rest_url(self) -> str:
        return f"{self.url.rstrip('/')}/rest/v1"

    @property
    def auth_url(self) -> str:
        return f"{self.url.rstrip('/')}/auth/v1"

    @property
    def realtime_websocket_url(self) -> str:
        parsed = urlparse(self.url.rstrip("/"))
        return f"wss://{parsed.netloc}/realtime/v1/websocket"
