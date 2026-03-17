"""Upstash Redis queue client backed by Redis list commands."""
from __future__ import annotations

import json
import os
from typing import Any, Mapping, Sequence

from integrations.config import UpstashRedisConfig
from integrations.errors import ConfigurationError

try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover - exercised in environments without redis installed
    redis = None


class UpstashRedisQueue:
    """Simple LPUSH/BRPOP wrapper for queueing JSON job payloads."""

    PRIORITY_LEVELS = ("high", "normal", "low")

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
        self._priority_queue_map = {
            "high": (os.getenv("UPSTASH_REDIS_HIGH_QUEUE_NAME") or "").strip(),
            "normal": (os.getenv("UPSTASH_REDIS_NORMAL_QUEUE_NAME") or "").strip(),
            "low": (os.getenv("UPSTASH_REDIS_LOW_QUEUE_NAME") or "").strip(),
        }

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

    @classmethod
    def normalize_priority(cls, priority: str | None) -> str:
        text = str(priority or "").strip().lower()
        if text in {"high", "urgent", "critical"}:
            return "high"
        if text in {"low", "background"}:
            return "low"
        if text in {"normal", "default", "medium", "standard", ""}:
            return "normal"
        return "normal"

    def queue_name_for_priority(self, priority: str | None) -> str:
        normalized = self.normalize_priority(priority)
        if normalized == "normal":
            override = self._priority_queue_map.get("normal")
            return override or self.queue_name

        override = self._priority_queue_map.get(normalized)
        if override:
            return override
        return f"{self.queue_name}:{normalized}"

    @property
    def priority_queue_names(self) -> tuple[str, str, str]:
        return (
            self.queue_name_for_priority("high"),
            self.queue_name_for_priority("normal"),
            self.queue_name_for_priority("low"),
        )

    def push_job(
        self,
        payload: Mapping[str, Any],
        *,
        queue_name: str | None = None,
        priority: str | None = None,
    ) -> int:
        payload_priority = payload.get("priority") if isinstance(payload, Mapping) else None
        normalized_priority = self.normalize_priority(priority if priority is not None else payload_priority)
        message = dict(payload)
        message.setdefault("priority", normalized_priority)

        encoded = json.dumps(message, separators=(",", ":"), ensure_ascii=True)
        target_queue = str(queue_name or self.queue_name_for_priority(normalized_priority)).strip() or self.queue_name
        size = self._client.lpush(target_queue, encoded)
        return int(size)

    def blocking_pop(
        self,
        timeout_seconds: int | None = None,
        *,
        queue_names: Sequence[str] | None = None,
    ) -> dict[str, Any] | None:
        timeout = self.config.pop_timeout_seconds if timeout_seconds is None else max(0, int(timeout_seconds))
        queues = self._resolve_queue_names(queue_names)
        key_arg: str | Sequence[str] = queues[0] if len(queues) == 1 else queues
        item = self._client.brpop(key_arg, timeout=timeout)
        if not item:
            return None

        popped_queue, raw_value = item
        queue_name = popped_queue.decode("utf-8", errors="replace") if isinstance(popped_queue, bytes) else str(popped_queue)
        payload = self._decode_payload(raw_value)
        if "priority" not in payload:
            payload["priority"] = self._priority_from_queue_name(queue_name)
        return payload

    def pop_nowait(self, *, queue_names: Sequence[str] | None = None) -> dict[str, Any] | None:
        queues = self._resolve_queue_names(queue_names)
        rpop = getattr(self._client, "rpop", None)
        if rpop is None:
            return None

        for queue_name in queues:
            raw_value = rpop(queue_name)
            if raw_value is None:
                continue

            payload = self._decode_payload(raw_value)
            if "priority" not in payload:
                payload["priority"] = self._priority_from_queue_name(queue_name)
            return payload

        return None

    def blocking_pop_many(
        self,
        *,
        batch_size: int,
        timeout_seconds: int | None = None,
        queue_names: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        target_size = max(1, int(batch_size))
        first = self.blocking_pop(timeout_seconds=timeout_seconds, queue_names=queue_names)
        if first is None:
            return []

        items = [first]
        while len(items) < target_size:
            nxt = self.pop_nowait(queue_names=queue_names)
            if nxt is None:
                break
            items.append(nxt)
        return items

    def queue_depth(self, *, queue_name: str | None = None) -> int:
        target_queue = str(queue_name or self.queue_name).strip() or self.queue_name
        depth = self._client.llen(target_queue)
        return int(depth)

    def queue_depth_many(self, *, queue_names: Sequence[str] | None = None) -> int:
        return sum(self.queue_depth(queue_name=name) for name in self._resolve_queue_names(queue_names))

    def _resolve_queue_names(self, queue_names: Sequence[str] | None) -> tuple[str, ...]:
        if queue_names:
            normalized = [str(name).strip() for name in queue_names if str(name).strip()]
            if normalized:
                return tuple(normalized)
        return self.priority_queue_names

    def _priority_from_queue_name(self, queue_name: str) -> str:
        normalized_name = str(queue_name or "").strip()
        if normalized_name == self.queue_name_for_priority("high"):
            return "high"
        if normalized_name == self.queue_name_for_priority("low"):
            return "low"
        return "normal"

    @staticmethod
    def _decode_payload(raw_value: Any) -> dict[str, Any]:
        if isinstance(raw_value, bytes):
            decoded = raw_value.decode("utf-8", errors="replace")
        else:
            decoded = str(raw_value)

        payload = json.loads(decoded)
        if not isinstance(payload, dict):
            raise ValueError("Queue payload must decode to a JSON object.")
        return payload
