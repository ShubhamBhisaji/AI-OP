"""Upstash Redis queue client backed by Redis list commands."""
from __future__ import annotations

import json
import os
from typing import Any, Mapping

from integrations.config import UpstashRedisConfig
from integrations.errors import ConfigurationError

try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover - exercised in environments without redis installed
    redis = None


class UpstashRedisQueue:
    """Simple LPUSH/BRPOP wrapper for queueing JSON job payloads."""

    def __init__(
        self,
        config: UpstashRedisConfig | None = None,
        *,
        client: Any = None,
    ) -> None:
        if config is None and client is not None:
            config = UpstashRedisConfig(
                redis_url="rediss://local-placeholder",
                queue_name=(os.getenv("UPSTASH_REDIS_QUEUE_NAME") or "job_queue").strip() or "job_queue",
                pop_timeout_seconds=30,
                socket_timeout_seconds=90,
            )

        self.config = config or UpstashRedisConfig.from_env()
        self.queue_name = self.config.queue_name

        if client is not None:
            self._client = client
            return

        if redis is None:
            raise ConfigurationError(
                "redis package is required for Upstash queue integration. Install with: pip install redis>=5.0.0"
            )

        self._client = redis.Redis.from_url(
            self.config.redis_url,
            decode_responses=True,
            socket_timeout=self.config.socket_timeout_seconds,
            socket_connect_timeout=self.config.socket_timeout_seconds,
            retry_on_timeout=True,
        )

    def push_job(self, payload: Mapping[str, Any]) -> int:
        encoded = json.dumps(dict(payload), separators=(",", ":"), ensure_ascii=True)
        size = self._client.lpush(self.queue_name, encoded)
        return int(size)

    def blocking_pop(self, timeout_seconds: int | None = None) -> dict[str, Any] | None:
        timeout = self.config.pop_timeout_seconds if timeout_seconds is None else max(0, int(timeout_seconds))
        item = self._client.brpop(self.queue_name, timeout=timeout)
        if not item:
            return None

        _, raw_value = item
        if isinstance(raw_value, bytes):
            decoded = raw_value.decode("utf-8", errors="replace")
        else:
            decoded = str(raw_value)

        payload = json.loads(decoded)
        if not isinstance(payload, dict):
            raise ValueError("Queue payload must decode to a JSON object.")
        return payload

    def queue_depth(self) -> int:
        depth = self._client.llen(self.queue_name)
        return int(depth)
