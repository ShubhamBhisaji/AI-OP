"""
AetheerGateway — Agent-Native Rate-Limiting & Request Batching Proxy.

In 2026, a single AetheerAI workflow can fire thousands of API calls in
milliseconds.  Without throttling, receiving services (Slack, Jira, Salesforce,
your own REST APIs) see the traffic as a DDoS attack and block the agent.

The Aetheer Gateway makes AetheerAI a "Good Citizen":

- Per-destination rate limiting  (token-bucket algorithm)
- Request queuing & smart batching  (group small payloads before sending)
- Backoff / retry on 429 / 503  (exponential back-off with jitter)
- Live metrics  (requests sent, queued, rejected, avg latency)

Architecture
------------
  GatewayDestination  — per-host config (rate, burst, batch_size, timeout)
  TokenBucket         — classic token-bucket rate limiter
  RequestBatch        — accumulates requests and flushes as a single call
  AetheerGateway      — thread-safe facade; call gateway.send() instead of
                        urllib.request.urlopen() or requests.get()

Usage
-----
    gw = AetheerGateway()
    gw.register("slack",  rate=5,  burst=10, base_url="https://slack.com/api")
    gw.register("jira",   rate=10, burst=20, base_url="https://company.atlassian.net")

    # Drop-in replacement for HTTP calls — gateway handles throttling:
    resp = gw.send("slack", "/chat.postMessage",
                   method="POST",
                   headers={"Authorization": "Bearer TOKEN"},
                   body={"channel": "#ops", "text": "Agent done."})

    # Or batch multiple small payloads:
    gw.enqueue("jira", "/rest/api/3/issue", body={"fields": {...}})
    gw.enqueue("jira", "/rest/api/3/issue", body={"fields": {...}})
    results = gw.flush_batch("jira")   # sends all at once, respecting rate limit
"""

from __future__ import annotations

import json
import logging
import math
import queue
import socket as _socket
import ipaddress
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Default limits ────────────────────────────────────────────────────────

DEFAULT_RATE = 10        # requests per second
DEFAULT_BURST = 20       # max burst tokens
DEFAULT_TIMEOUT = 30     # HTTP timeout in seconds
DEFAULT_MAX_RETRIES = 4  # on 429 / 5xx
DEFAULT_BATCH_SIZE = 10  # requests grouped per flush

# ── SSRF block-list — private / internal IP ranges ───────────────────────────
# Prevents agents from being tricked into calling cloud metadata endpoints,
# internal services, or loopback addresses (BLOCKER-3 fix).
_SSRF_BLOCKED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("127.0.0.0/8"),      # loopback
    ipaddress.ip_network("10.0.0.0/8"),       # RFC-1918 private
    ipaddress.ip_network("172.16.0.0/12"),    # RFC-1918 private
    ipaddress.ip_network("192.168.0.0/16"),   # RFC-1918 private
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / AWS metadata
    ipaddress.ip_network("100.64.0.0/10"),    # shared address space (RFC-6598)
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 unique-local
    ipaddress.ip_network("fe80::/10"),         # IPv6 link-local
]


def _assert_no_ssrf(url: str) -> None:
    """
    Raise ValueError if *url* resolves to a private, loopback, or
    link-local IP address (SSRF prevention).
    """
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"[SSRF-BLOCK] Invalid URL (no hostname): {url}")
    try:
        ip = ipaddress.ip_address(_socket.gethostbyname(hostname))
    except (_socket.gaierror, ValueError):
        # DNS resolution failed or already an IP literal that didn't parse —
        # let it through to get a proper HTTP error rather than a bypass path.
        return
    for net in _SSRF_BLOCKED_NETWORKS:
        if ip in net:
            raise ValueError(
                f"[SSRF-BLOCK] Destination '{url}' resolves to internal address "
                f"{ip} (network {net}). Request denied by AetheerGateway security policy."
            )


# ═══════════════════════════════════════════════════════════════════════════
# Token Bucket
# ═══════════════════════════════════════════════════════════════════════════


class TokenBucket:
    """
    Thread-safe token-bucket rate limiter.

    Parameters
    ----------
    rate  : tokens refilled per second
    burst : maximum token capacity (allows short bursts)
    """

    def __init__(self, rate: float, burst: float):
        self.rate = rate
        self.burst = burst
        self._tokens = burst
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, tokens: float = 1.0, block: bool = True) -> bool:
        """
        Consume `tokens` from the bucket.

        If `block` is True, sleeps until tokens are available.
        Returns True if tokens were consumed, False if non-blocking and unavailable.
        """
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                if not block:
                    return False
                # Calculate wait time
                deficit = tokens - self._tokens
                wait = deficit / self.rate

            time.sleep(wait)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._last_refill = now

    @property
    def available(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens


# ═══════════════════════════════════════════════════════════════════════════
# Gateway Destination config
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class GatewayDestination:
    name: str
    base_url: str
    rate: float = DEFAULT_RATE          # requests/second
    burst: float = DEFAULT_BURST
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    batch_size: int = DEFAULT_BATCH_SIZE
    default_headers: dict = field(default_factory=dict)

    # Runtime (not serialised)
    _bucket: TokenBucket = field(init=False, repr=False)
    _batch_queue: list = field(default_factory=list, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _metrics: dict = field(default_factory=lambda: {
        "sent": 0, "queued": 0, "retried": 0, "errors": 0,
        "total_latency_ms": 0.0, "throttled_ms": 0.0,
    }, init=False, repr=False)

    def __post_init__(self):
        self._bucket = TokenBucket(self.rate, self.burst)
        self._batch_queue = []
        self._lock = threading.Lock()
        self._metrics = {
            "sent": 0, "queued": 0, "retried": 0, "errors": 0,
            "total_latency_ms": 0.0, "throttled_ms": 0.0,
        }

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "rate_rps": self.rate,
            "burst": self.burst,
            "timeout_s": self.timeout,
            "max_retries": self.max_retries,
            "batch_size": self.batch_size,
            "tokens_available": round(self._bucket.available, 2),
            **self._metrics,
            "avg_latency_ms": (
                round(self._metrics["total_latency_ms"] / max(1, self._metrics["sent"]), 1)
            ),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Aetheer Gateway
# ═══════════════════════════════════════════════════════════════════════════


class AetheerGateway:
    """
    Thread-safe rate-limiting gateway for all agent-originated HTTP calls.

    Register destinations once at startup; call `send()` anywhere in agent
    code instead of raw urllib / requests.
    """

    def __init__(self):
        self._destinations: dict[str, GatewayDestination] = {}
        self._lock = threading.Lock()

    # ── Registration ──────────────────────────────────────────────────

    def register(
        self,
        name: str,
        base_url: str,
        rate: float = DEFAULT_RATE,
        burst: float = DEFAULT_BURST,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        batch_size: int = DEFAULT_BATCH_SIZE,
        default_headers: dict | None = None,
    ) -> None:
        """Register a rate-limited destination."""
        # BLOCKER-3: Validate base_url is not an internal/private address.
        _assert_no_ssrf(base_url)
        dest = GatewayDestination(
            name=name,
            base_url=base_url.rstrip("/"),
            rate=rate,
            burst=burst,
            timeout=timeout,
            max_retries=max_retries,
            batch_size=batch_size,
            default_headers=default_headers or {},
        )
        with self._lock:
            self._destinations[name] = dest
        logger.info(
            "Gateway: registered '%s' at %s (rate=%.1f/s burst=%.0f)",
            name, base_url, rate, burst,
        )

    def unregister(self, name: str) -> bool:
        with self._lock:
            if name in self._destinations:
                del self._destinations[name]
                return True
        return False

    def list_destinations(self) -> list[dict]:
        with self._lock:
            return [d.to_dict() for d in self._destinations.values()]

    # ── Direct send (rate-limited, auto-retry) ────────────────────────

    def send(
        self,
        destination: str,
        path: str,
        *,
        method: str = "GET",
        headers: dict | None = None,
        body: dict | Any = None,
        params: dict | None = None,
    ) -> dict:
        """
        Send a rate-limited HTTP request to a registered destination.

        Parameters
        ----------
        destination : Registered destination name.
        path        : URL path suffix (e.g. "/chat.postMessage").
        method      : HTTP verb. Default "GET".
        headers     : Extra headers merged with destination defaults.
        body        : Request body (serialized to JSON automatically).
        params      : Query-string parameters.

        Returns
        -------
        dict with keys: status_code, body (parsed JSON or str), latency_ms
        """
        dest = self._get_dest(destination)
        url = dest.base_url + path
        # BLOCKER-3: Re-validate full URL at send time to catch path-traversal tricks.
        _assert_no_ssrf(url)
        if params:
            url = url + "?" + urllib.parse.urlencode(params)

        merged_headers = {**dest.default_headers, **(headers or {})}
        data = None
        if body is not None:
            if "Content-Type" not in merged_headers:
                merged_headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()

        attempt = 0
        while True:
            # Throttle — wait for token
            t0 = time.monotonic()
            dest._bucket.consume(1.0, block=True)
            throttle_ms = (time.monotonic() - t0) * 1000
            dest._metrics["throttled_ms"] += throttle_ms

            req = urllib.request.Request(
                url, data=data, headers=merged_headers, method=method.upper()
            )
            t_send = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=dest.timeout) as resp:
                    raw = resp.read().decode()
                    latency_ms = (time.monotonic() - t_send) * 1000
                    dest._metrics["sent"] += 1
                    dest._metrics["total_latency_ms"] += latency_ms
                    try:
                        parsed = json.loads(raw)
                    except Exception:
                        parsed = raw
                    return {
                        "status_code": resp.status,
                        "body": parsed,
                        "latency_ms": round(latency_ms, 1),
                        "throttled_ms": round(throttle_ms, 1),
                    }

            except urllib.error.HTTPError as exc:
                latency_ms = (time.monotonic() - t_send) * 1000
                if exc.code in (429, 503, 502, 504):
                    attempt += 1
                    if attempt > dest.max_retries:
                        dest._metrics["errors"] += 1
                        raise RuntimeError(
                            f"Gateway '{destination}': {exc.code} after "
                            f"{attempt} retries on {url}"
                        ) from exc
                    # Exponential back-off with jitter
                    backoff = min(60, (2 ** attempt) + (time.monotonic() % 1))
                    logger.warning(
                        "Gateway '%s': %d received — backing off %.1fs (attempt %d/%d)",
                        destination, exc.code, backoff, attempt, dest.max_retries,
                    )
                    dest._metrics["retried"] += 1
                    time.sleep(backoff)
                else:
                    dest._metrics["errors"] += 1
                    raise RuntimeError(
                        f"Gateway '{destination}': HTTP {exc.code} on {url}"
                    ) from exc

            except Exception as exc:
                dest._metrics["errors"] += 1
                raise RuntimeError(
                    f"Gateway '{destination}': request failed — {exc}"
                ) from exc

    # ── Batching ──────────────────────────────────────────────────────

    def enqueue(
        self,
        destination: str,
        path: str,
        *,
        method: str = "POST",
        headers: dict | None = None,
        body: dict | Any = None,
        params: dict | None = None,
    ) -> int:
        """
        Enqueue a request for batch sending. Returns current queue depth.
        Call flush_batch() to send all queued requests.
        """
        dest = self._get_dest(destination)
        with dest._lock:
            dest._batch_queue.append({
                "path": path,
                "method": method,
                "headers": headers,
                "body": body,
                "params": params,
            })
            dest._metrics["queued"] += 1
            depth = len(dest._batch_queue)
        logger.debug("Gateway '%s': queued request — depth=%d", destination, depth)
        return depth

    def flush_batch(self, destination: str) -> list[dict]:
        """
        Send all enqueued requests to `destination` in batches,
        respecting the rate limit between each.

        Returns a list of response dicts (one per request).
        """
        dest = self._get_dest(destination)
        with dest._lock:
            batch = list(dest._batch_queue)
            dest._batch_queue.clear()

        if not batch:
            return []

        results = []
        for req in batch:
            try:
                result = self.send(
                    destination,
                    req["path"],
                    method=req["method"],
                    headers=req["headers"],
                    body=req["body"],
                    params=req["params"],
                )
                results.append({"ok": True, **result})
            except Exception as exc:
                results.append({"ok": False, "error": str(exc)})

        logger.info(
            "Gateway '%s': flushed %d requests, %d ok",
            destination,
            len(batch),
            sum(1 for r in results if r.get("ok")),
        )
        return results

    def queue_depth(self, destination: str) -> int:
        dest = self._get_dest(destination)
        with dest._lock:
            return len(dest._batch_queue)

    # ── Metrics ───────────────────────────────────────────────────────

    def metrics(self, destination: str | None = None) -> dict:
        """Return metrics for one or all destinations."""
        if destination:
            return self._get_dest(destination).to_dict()
        with self._lock:
            return {name: d.to_dict() for name, d in self._destinations.items()}

    def reset_metrics(self, destination: str | None = None) -> None:
        """Reset counters for one or all destinations."""
        targets = (
            [self._get_dest(destination)]
            if destination
            else list(self._destinations.values())
        )
        for d in targets:
            d._metrics = {
                "sent": 0, "queued": 0, "retried": 0, "errors": 0,
                "total_latency_ms": 0.0, "throttled_ms": 0.0,
            }

    # ── Internal ──────────────────────────────────────────────────────

    def _get_dest(self, name: str) -> GatewayDestination:
        with self._lock:
            dest = self._destinations.get(name)
        if dest is None:
            raise KeyError(
                f"No gateway destination '{name}'. "
                f"Register it first with gateway.register(). "
                f"Available: {list(self._destinations)}"
            )
        return dest
