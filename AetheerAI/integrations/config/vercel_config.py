"""Environment-driven settings for Vercel integration."""
from __future__ import annotations

from dataclasses import dataclass

from .base_config import env_int, env_optional, env_required


@dataclass(slots=True, frozen=True)
class VercelConfig:
    api_token: str
    api_base_url: str
    team_id: str
    project_id: str
    timeout_seconds: int

    @classmethod
    def from_env(cls) -> "VercelConfig":
        return cls(
            api_token=env_required("VERCEL_API_TOKEN"),
            api_base_url=env_optional("VERCEL_API_BASE_URL", "https://api.vercel.com"),
            team_id=env_optional("VERCEL_TEAM_ID"),
            project_id=env_optional("VERCEL_PROJECT_ID"),
            timeout_seconds=env_int("VERCEL_TIMEOUT_SECONDS", 20),
        )
