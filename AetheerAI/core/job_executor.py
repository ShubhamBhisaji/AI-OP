"""Job execution backends for scheduler dispatch.

Decouples queue management from execution transport so the scheduler can run:
- locally (in-process, default)
- through a distributed HTTP worker endpoint (optional)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class JobExecutor(Protocol):
    """Execution contract consumed by the kernel/scheduler boundary."""

    def execute(self, agent_name: str, task: str) -> Any:
        ...

    def info(self) -> dict[str, Any]:
        ...


@dataclass
class LocalJobExecutor:
    """Default in-process executor that directly calls kernel.run_agent()."""

    runner: Callable[[str, str], Any]

    def execute(self, agent_name: str, task: str) -> Any:
        return self.runner(agent_name, task)

    def info(self) -> dict[str, Any]:
        return {
            "mode": "local",
            "transport": "in_process",
        }


@dataclass
class DistributedHTTPJobExecutor:
    """Dispatches jobs to a remote worker API over HTTP."""

    endpoint: str
    timeout_seconds: float = 60.0
    local_fallback: Callable[[str, str], Any] | None = None
    auth_token: str | None = None

    def __post_init__(self) -> None:
        self.endpoint = self.endpoint.strip().rstrip("/")
        if not self.endpoint:
            raise ValueError("DistributedHTTPJobExecutor endpoint cannot be empty.")
        if self.auth_token is None:
            token = (os.environ.get("AETHEERAI_DISTRIBUTED_EXECUTOR_TOKEN") or "").strip()
            self.auth_token = token or None

    def execute(self, agent_name: str, task: str) -> Any:
        payload = {
            "agent_name": agent_name,
            "task": task,
        }
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
            return self._decode_response(body)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            if self.local_fallback is not None:
                logger.warning(
                    "Distributed executor failed (%s); falling back to local runner.",
                    exc,
                )
                return self.local_fallback(agent_name, task)
            raise RuntimeError(f"Distributed job execution failed: {exc}") from exc

    @staticmethod
    def _decode_response(body: str) -> Any:
        if not body:
            return ""

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            # Allow plain-text workers.
            return body

        if isinstance(parsed, dict):
            if parsed.get("success") is False:
                detail = parsed.get("detail") or parsed.get("error") or "Remote worker rejected job."
                raise RuntimeError(str(detail))
            data = parsed.get("data")
            if isinstance(data, dict) and "result" in data:
                return data["result"]
            if "result" in parsed:
                return parsed["result"]

        return parsed

    def info(self) -> dict[str, Any]:
        return {
            "mode": "distributed",
            "transport": "http",
            "endpoint": self.endpoint,
            "fallback_enabled": self.local_fallback is not None,
            "timeout_seconds": self.timeout_seconds,
        }


def build_job_executor(
    local_runner: Callable[[str, str], Any],
    *,
    env: Mapping[str, str] | None = None,
) -> JobExecutor:
    """Select local or distributed executor based on environment settings."""
    source = env if env is not None else os.environ

    endpoint = (source.get("AETHEERAI_DISTRIBUTED_EXECUTOR_URL") or "").strip()
    if not endpoint:
        return LocalJobExecutor(runner=local_runner)

    timeout_raw = (source.get("AETHEERAI_DISTRIBUTED_EXECUTOR_TIMEOUT_SEC") or "60").strip()
    try:
        timeout_seconds = max(1.0, float(timeout_raw))
    except ValueError:
        timeout_seconds = 60.0

    fallback_raw = (source.get("AETHEERAI_DISTRIBUTED_EXECUTOR_FALLBACK_LOCAL") or "1").strip().lower()
    fallback_enabled = fallback_raw not in {"0", "false", "no", "off"}

    token = (source.get("AETHEERAI_DISTRIBUTED_EXECUTOR_TOKEN") or "").strip() or None
    fallback = local_runner if fallback_enabled else None

    return DistributedHTTPJobExecutor(
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        local_fallback=fallback,
        auth_token=token,
    )
