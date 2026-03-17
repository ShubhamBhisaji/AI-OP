"""Production runtime helpers for request control, telemetry, and failover state."""

from __future__ import annotations

import os
import re
import threading
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Any


_AI_FAILURE_RE = re.compile(
    r"timeout|timed out|connection|dns|rate\\s*limit|429|503|gateway|provider|model|api\\s*key|auth|overload",
    re.IGNORECASE,
)


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    if minimum is not None:
        return max(minimum, value)
    return value


def _env_first(*names: str) -> str:
    for name in names:
        raw = os.getenv(name, "")
        if raw and raw.strip():
            return raw.strip()
    return ""


def _env_float(name: str, default: float, minimum: float | None = None) -> float:
    raw = os.getenv(name, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    if minimum is not None:
        return max(minimum, value)
    return value


@dataclass(frozen=True)
class RuntimeConfig:
    max_concurrent_requests: int = 64
    request_queue_timeout_seconds: float = 2.0
    rate_limit_rpm: int = 0
    trace_buffer_size: int = 300
    failover_failure_threshold: int = 3
    failover_cooldown_seconds: float = 30.0
    failover_provider: str = ""
    failover_model: str = ""

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        def _to_int(raw: str, default: int, minimum: int) -> int:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                value = default
            return max(minimum, value)

        def _to_float(raw: str, default: float, minimum: float) -> float:
            try:
                value = float(raw)
            except (TypeError, ValueError):
                value = default
            return max(minimum, value)

        max_concurrency_raw = _env_first("AETHEER_MAX_CONCURRENT_REQUESTS", "AETHER_MAX_CONCURRENT_REQUESTS")
        queue_timeout_raw = _env_first("AETHEER_REQUEST_QUEUE_TIMEOUT_SECONDS", "AETHER_REQUEST_QUEUE_TIMEOUT_SECONDS")
        rate_limit_raw = _env_first("AETHEER_RATE_LIMIT_RPM", "AETHER_RATE_LIMIT_RPM")
        trace_buffer_raw = _env_first("AETHEER_TRACE_BUFFER_SIZE", "AETHER_TRACE_BUFFER_SIZE")
        fail_threshold_raw = _env_first("AETHEER_FAILOVER_FAILURE_THRESHOLD", "AETHER_FAILOVER_FAILURE_THRESHOLD")
        fail_cooldown_raw = _env_first("AETHEER_FAILOVER_COOLDOWN_SECONDS", "AETHER_FAILOVER_COOLDOWN_SECONDS")
        fail_provider = _env_first("AETHEER_FAILOVER_PROVIDER", "AETHER_FAILOVER_PROVIDER").lower()
        fail_model = _env_first("AETHEER_FAILOVER_MODEL", "AETHER_FAILOVER_MODEL")

        return cls(
            max_concurrent_requests=_to_int(max_concurrency_raw, 64, 1),
            request_queue_timeout_seconds=_to_float(queue_timeout_raw, 2.0, 0.05),
            rate_limit_rpm=_to_int(rate_limit_raw, 0, 0),
            trace_buffer_size=_to_int(trace_buffer_raw, 300, 25),
            failover_failure_threshold=_to_int(fail_threshold_raw, 3, 1),
            failover_cooldown_seconds=_to_float(fail_cooldown_raw, 30.0, 1.0),
            failover_provider=fail_provider,
            failover_model=fail_model,
        )


class TTLResponseCache:
    """Small thread-safe TTL cache for lightweight API responses."""

    def __init__(self, max_entries: int = 64) -> None:
        self._max_entries = max(1, int(max_entries))
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        now = time.time()
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            expires_at, payload = item
            if expires_at <= now:
                self._store.pop(key, None)
                return None
            return payload

    def set(self, key: str, payload: Any, ttl_seconds: float) -> None:
        ttl = max(0.01, float(ttl_seconds))
        expires_at = time.time() + ttl
        with self._lock:
            if len(self._store) >= self._max_entries:
                # Opportunistic bounded eviction: remove oldest expiration.
                oldest_key = min(self._store, key=lambda item_key: self._store[item_key][0])
                self._store.pop(oldest_key, None)
            self._store[key] = (expires_at, payload)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)


class ProductionRuntime:
    """Tracks runtime request health, traces, and AI failover eligibility."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self._lock = threading.Lock()

        self._requests_total = 0
        self._errors_total = 0
        self._rejected_total = 0
        self._latency_total_ms = 0.0
        self._status_totals: Counter[str] = Counter()
        self._path_counts: dict[str, int] = defaultdict(int)
        self._path_latency_ms: dict[str, float] = defaultdict(float)

        self._in_flight = 0
        self._max_in_flight_seen = 0

        self._rate_windows: dict[str, deque[float]] = defaultdict(deque)
        self._traces: deque[dict[str, Any]] = deque(maxlen=config.trace_buffer_size)

        self._ai_failure_streak = 0
        self._last_ai_error = ""
        self._failover_block_until = 0.0
        self._failover_activations = 0
        self._last_failover_at = 0.0
        self._last_failover_reason = ""

    @property
    def failover_enabled(self) -> bool:
        return bool(self.config.failover_provider)

    def allow_request(self, client_id: str, now: float | None = None) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        if self.config.rate_limit_rpm <= 0:
            return True, 0

        t_now = now if now is not None else time.time()
        key = client_id or "unknown"
        with self._lock:
            window = self._rate_windows[key]
            cutoff = t_now - 60.0
            while window and window[0] <= cutoff:
                window.popleft()

            if len(window) >= self.config.rate_limit_rpm:
                retry_after = int(max(1.0, 60.0 - (t_now - window[0])))
                return False, retry_after

            window.append(t_now)
            if len(window) == 0:
                self._rate_windows.pop(key, None)
            return True, 0

    def begin_request(self) -> None:
        with self._lock:
            self._in_flight += 1
            if self._in_flight > self._max_in_flight_seen:
                self._max_in_flight_seen = self._in_flight

    def end_request(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        latency_ms: float,
        request_id: str,
        client_id: str,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._record_request_locked(
                method=method,
                path=path,
                status_code=status_code,
                latency_ms=latency_ms,
                request_id=request_id,
                client_id=client_id,
                error=error,
            )

    def record_rejected_request(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        latency_ms: float,
        request_id: str,
        client_id: str,
        error: str,
    ) -> None:
        with self._lock:
            self._rejected_total += 1
            self._record_request_locked(
                method=method,
                path=path,
                status_code=status_code,
                latency_ms=latency_ms,
                request_id=request_id,
                client_id=client_id,
                error=error,
            )

    def _record_request_locked(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        latency_ms: float,
        request_id: str,
        client_id: str,
        error: str | None,
    ) -> None:
        self._requests_total += 1
        self._latency_total_ms += max(0.0, float(latency_ms))
        status_bucket = f"{int(status_code) // 100}xx"
        self._status_totals[status_bucket] += 1
        normalized_path = path or "/"
        self._path_counts[normalized_path] += 1
        self._path_latency_ms[normalized_path] += max(0.0, float(latency_ms))

        if int(status_code) >= 500:
            self._errors_total += 1

        self._traces.append(
            {
                "ts": time.time(),
                "request_id": request_id,
                "client": client_id,
                "method": method,
                "path": normalized_path,
                "status_code": int(status_code),
                "latency_ms": round(max(0.0, float(latency_ms)), 3),
                "error": (error or "")[:300],
            }
        )

    def metrics_snapshot(self) -> dict[str, Any]:
        with self._lock:
            request_total = self._requests_total
            avg_latency = self._latency_total_ms / max(1, request_total)
            return {
                "requests_total": request_total,
                "errors_total": self._errors_total,
                "rejected_total": self._rejected_total,
                "in_flight": self._in_flight,
                "max_in_flight_seen": self._max_in_flight_seen,
                "avg_latency_ms": round(avg_latency, 3),
                "rate_limit_rpm": self.config.rate_limit_rpm,
                "max_concurrent_requests": self.config.max_concurrent_requests,
                "status_totals": dict(self._status_totals),
                "top_paths": self._build_top_paths_locked(limit=12),
            }

    def recent_traces(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), self.config.trace_buffer_size))
        with self._lock:
            rows = list(self._traces)[-safe_limit:]
        rows.reverse()
        return rows

    def record_ai_failure(self, error_text: str) -> bool:
        """Return True when failover activation should be attempted."""
        if not self.failover_enabled:
            return False
        if not _AI_FAILURE_RE.search(error_text or ""):
            return False

        now = time.time()
        with self._lock:
            self._ai_failure_streak += 1
            self._last_ai_error = (error_text or "")[:500]
            if self._ai_failure_streak >= self.config.failover_failure_threshold and now >= self._failover_block_until:
                self._failover_block_until = now + self.config.failover_cooldown_seconds
                return True
        return False

    def record_ai_success(self) -> None:
        with self._lock:
            self._ai_failure_streak = 0

    def mark_failover_activated(self, reason: str) -> None:
        with self._lock:
            self._failover_activations += 1
            self._last_failover_at = time.time()
            self._last_failover_reason = (reason or "")[:500]
            self._ai_failure_streak = 0

    def mark_failover_activation_failed(self, error_text: str) -> None:
        with self._lock:
            self._last_failover_reason = f"activation_failed:{(error_text or '')[:500]}"

    def failover_state(self, active_provider: str, active_model: str) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.failover_enabled,
                "configured_provider": self.config.failover_provider,
                "configured_model": self.config.failover_model,
                "active_provider": active_provider,
                "active_model": active_model,
                "failure_streak": self._ai_failure_streak,
                "threshold": self.config.failover_failure_threshold,
                "cooldown_seconds": self.config.failover_cooldown_seconds,
                "cooldown_until": self._failover_block_until,
                "activations": self._failover_activations,
                "last_failover_at": self._last_failover_at,
                "last_reason": self._last_failover_reason,
                "last_ai_error": self._last_ai_error,
            }

    def prometheus_text(self, instance_id: str, uptime_seconds: float) -> str:
        snap = self.metrics_snapshot()
        fail = self.failover_state(
            active_provider=snap.get("active_provider", ""),
            active_model=snap.get("active_model", ""),
        )

        escaped_instance = _escape_metric_label(instance_id)
        lines = [
            "# HELP aetheer_requests_total Total processed HTTP requests.",
            "# TYPE aetheer_requests_total counter",
            f'aetheer_requests_total{{instance="{escaped_instance}"}} {snap["requests_total"]}',
            "# HELP aetheer_errors_total Total HTTP responses with status >= 500.",
            "# TYPE aetheer_errors_total counter",
            f'aetheer_errors_total{{instance="{escaped_instance}"}} {snap["errors_total"]}',
            "# HELP aetheer_rejected_total Total rejected requests due to rate-limit/backpressure.",
            "# TYPE aetheer_rejected_total counter",
            f'aetheer_rejected_total{{instance="{escaped_instance}"}} {snap["rejected_total"]}',
            "# HELP aetheer_request_latency_ms_avg Average request latency in milliseconds.",
            "# TYPE aetheer_request_latency_ms_avg gauge",
            f'aetheer_request_latency_ms_avg{{instance="{escaped_instance}"}} {snap["avg_latency_ms"]}',
            "# HELP aetheer_requests_in_flight Current in-flight requests.",
            "# TYPE aetheer_requests_in_flight gauge",
            f'aetheer_requests_in_flight{{instance="{escaped_instance}"}} {snap["in_flight"]}',
            "# HELP aetheer_uptime_seconds Process uptime in seconds.",
            "# TYPE aetheer_uptime_seconds gauge",
            f'aetheer_uptime_seconds{{instance="{escaped_instance}"}} {round(max(0.0, uptime_seconds), 3)}',
            "# HELP aetheer_failover_activations_total Number of automatic failover activations.",
            "# TYPE aetheer_failover_activations_total counter",
            f'aetheer_failover_activations_total{{instance="{escaped_instance}"}} {fail["activations"]}',
            "# HELP aetheer_failover_enabled Whether automatic failover is configured.",
            "# TYPE aetheer_failover_enabled gauge",
            f'aetheer_failover_enabled{{instance="{escaped_instance}"}} {1 if fail["enabled"] else 0}',
        ]

        for bucket, count in sorted(snap["status_totals"].items()):
            escaped_bucket = _escape_metric_label(bucket)
            lines.extend(
                [
                    "# HELP aetheer_http_responses_total Count of responses by status class.",
                    "# TYPE aetheer_http_responses_total counter",
                    (
                        f'aetheer_http_responses_total{{instance="{escaped_instance}",' 
                        f'status="{escaped_bucket}"}} {count}'
                    ),
                ]
            )

        return "\n".join(lines) + "\n"

    def _build_top_paths_locked(self, limit: int) -> list[dict[str, Any]]:
        items = sorted(self._path_counts.items(), key=lambda item: item[1], reverse=True)
        out: list[dict[str, Any]] = []
        for path, count in items[: max(1, int(limit))]:
            latency_total = self._path_latency_ms.get(path, 0.0)
            out.append(
                {
                    "path": path,
                    "count": count,
                    "avg_latency_ms": round(latency_total / max(1, count), 3),
                }
            )
        return out


def _escape_metric_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
