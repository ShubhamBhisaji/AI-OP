"""Environment-driven settings for Upstash Redis queue integration."""
from __future__ import annotations

from dataclasses import dataclass

from .base_config import env_int, env_optional, env_required


@dataclass(slots=True, frozen=True)
class UpstashRedisConfig:
    redis_url: str
    queue_name: str
    pop_timeout_seconds: int
    socket_timeout_seconds: int

    @classmethod
    def from_env(cls) -> "UpstashRedisConfig":
        return cls(
            redis_url=env_required("UPSTASH_REDIS_URL"),
            queue_name=env_optional("UPSTASH_REDIS_QUEUE_NAME", "job_queue"),
            pop_timeout_seconds=env_int("UPSTASH_REDIS_POP_TIMEOUT_SECONDS", 30),
            socket_timeout_seconds=env_int("UPSTASH_REDIS_SOCKET_TIMEOUT_SECONDS", 90),
        )
