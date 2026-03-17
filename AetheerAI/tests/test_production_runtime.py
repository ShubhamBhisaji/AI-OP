"""
Tests for core/production_runtime.py

Covers:
- RuntimeConfig defaults and from_env()
- TTLResponseCache get/set/invalidate/eviction
- ProductionRuntime: request tracking, rate limiting, failover state machine,
  metrics snapshot, traces, and Prometheus export
- Helper functions (_env_int, _env_float, _env_first, _escape_metric_label)
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.production_runtime import (
    ProductionRuntime,
    RuntimeConfig,
    TTLResponseCache,
    _env_float,
    _env_int,
    _env_first,
    _escape_metric_label,
)


# ---------------------------------------------------------------------------
# RuntimeConfig
# ---------------------------------------------------------------------------

class TestRuntimeConfigDefaults(unittest.TestCase):
    def test_default_values(self):
        cfg = RuntimeConfig()
        self.assertEqual(cfg.max_concurrent_requests, 64)
        self.assertEqual(cfg.request_queue_timeout_seconds, 2.0)
        self.assertEqual(cfg.rate_limit_rpm, 0)
        self.assertEqual(cfg.trace_buffer_size, 300)
        self.assertEqual(cfg.failover_failure_threshold, 3)
        self.assertEqual(cfg.failover_cooldown_seconds, 30.0)
        self.assertEqual(cfg.failover_provider, "")
        self.assertEqual(cfg.failover_model, "")

    def test_frozen(self):
        cfg = RuntimeConfig()
        with self.assertRaises(AttributeError):
            cfg.max_concurrent_requests = 999  # type: ignore[misc]


class TestRuntimeConfigFromEnv(unittest.TestCase):
    @patch.dict(os.environ, {
        "AETHEER_MAX_CONCURRENT_REQUESTS": "128",
        "AETHEER_REQUEST_QUEUE_TIMEOUT_SECONDS": "5.0",
        "AETHEER_RATE_LIMIT_RPM": "120",
        "AETHEER_TRACE_BUFFER_SIZE": "500",
        "AETHEER_FAILOVER_FAILURE_THRESHOLD": "5",
        "AETHEER_FAILOVER_COOLDOWN_SECONDS": "60",
        "AETHEER_FAILOVER_PROVIDER": "Anthropic",
        "AETHEER_FAILOVER_MODEL": "claude-3-5-sonnet",
    }, clear=False)
    def test_reads_env_vars(self):
        cfg = RuntimeConfig.from_env()
        self.assertEqual(cfg.max_concurrent_requests, 128)
        self.assertAlmostEqual(cfg.request_queue_timeout_seconds, 5.0)
        self.assertEqual(cfg.rate_limit_rpm, 120)
        self.assertEqual(cfg.trace_buffer_size, 500)
        self.assertEqual(cfg.failover_failure_threshold, 5)
        self.assertAlmostEqual(cfg.failover_cooldown_seconds, 60.0)
        self.assertEqual(cfg.failover_provider, "anthropic")  # lowercased
        self.assertEqual(cfg.failover_model, "claude-3-5-sonnet")

    @patch.dict(os.environ, {
        "AETHEER_MAX_CONCURRENT_REQUESTS": "not_a_number",
        "AETHEER_REQUEST_QUEUE_TIMEOUT_SECONDS": "abc",
        "AETHEER_RATE_LIMIT_RPM": "",
        "AETHEER_TRACE_BUFFER_SIZE": "0",
    }, clear=False)
    def test_malformed_env_uses_defaults_or_minimums(self):
        cfg = RuntimeConfig.from_env()
        # "not_a_number" -> falls back to default 64
        self.assertEqual(cfg.max_concurrent_requests, 64)
        # "abc" -> falls back to default 2.0
        self.assertAlmostEqual(cfg.request_queue_timeout_seconds, 2.0)
        # empty -> falls back to default 0
        self.assertEqual(cfg.rate_limit_rpm, 0)
        # "0" is valid int but minimum is 25
        self.assertEqual(cfg.trace_buffer_size, 25)

    @patch.dict(os.environ, {
        "AETHER_MAX_CONCURRENT_REQUESTS": "200",
    }, clear=False)
    def test_aether_prefix_fallback(self):
        """AETHER_ prefix (without extra E) should work as fallback."""
        # Remove the AETHEER_ version if present
        env = os.environ.copy()
        env.pop("AETHEER_MAX_CONCURRENT_REQUESTS", None)
        with patch.dict(os.environ, env, clear=True):
            os.environ["AETHER_MAX_CONCURRENT_REQUESTS"] = "200"
            cfg = RuntimeConfig.from_env()
            self.assertEqual(cfg.max_concurrent_requests, 200)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestEnvHelpers(unittest.TestCase):
    @patch.dict(os.environ, {"TEST_INT_VAR": "42"}, clear=False)
    def test_env_int_valid(self):
        self.assertEqual(_env_int("TEST_INT_VAR", 10), 42)

    @patch.dict(os.environ, {"TEST_INT_VAR": "bad"}, clear=False)
    def test_env_int_invalid(self):
        self.assertEqual(_env_int("TEST_INT_VAR", 10), 10)

    def test_env_int_missing(self):
        self.assertEqual(_env_int("NONEXISTENT_VAR_12345", 7), 7)

    @patch.dict(os.environ, {"TEST_INT_VAR": "3"}, clear=False)
    def test_env_int_minimum(self):
        self.assertEqual(_env_int("TEST_INT_VAR", 10, minimum=5), 5)

    @patch.dict(os.environ, {"TEST_FLOAT_VAR": "3.14"}, clear=False)
    def test_env_float_valid(self):
        self.assertAlmostEqual(_env_float("TEST_FLOAT_VAR", 1.0), 3.14)

    @patch.dict(os.environ, {"TEST_FLOAT_VAR": "nope"}, clear=False)
    def test_env_float_invalid(self):
        self.assertAlmostEqual(_env_float("TEST_FLOAT_VAR", 1.5), 1.5)

    @patch.dict(os.environ, {"A_VAR": "", "B_VAR": "hello"}, clear=False)
    def test_env_first_skips_empty(self):
        self.assertEqual(_env_first("A_VAR", "B_VAR"), "hello")

    def test_env_first_all_missing(self):
        self.assertEqual(_env_first("NO_SUCH_A", "NO_SUCH_B"), "")


class TestEscapeMetricLabel(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_escape_metric_label("hello"), "hello")

    def test_special_chars(self):
        self.assertEqual(_escape_metric_label('a"b\\c\nd'), 'a\\"b\\\\c d')


# ---------------------------------------------------------------------------
# TTLResponseCache
# ---------------------------------------------------------------------------

class TestTTLResponseCache(unittest.TestCase):
    def test_set_and_get(self):
        cache = TTLResponseCache(max_entries=10)
        cache.set("k1", {"data": 1}, ttl_seconds=10.0)
        self.assertEqual(cache.get("k1"), {"data": 1})

    def test_get_miss(self):
        cache = TTLResponseCache()
        self.assertIsNone(cache.get("missing"))

    def test_expiry(self):
        cache = TTLResponseCache()
        cache.set("k1", "val", ttl_seconds=0.01)
        time.sleep(0.05)
        self.assertIsNone(cache.get("k1"))

    def test_invalidate(self):
        cache = TTLResponseCache()
        cache.set("k1", "val", ttl_seconds=60.0)
        cache.invalidate("k1")
        self.assertIsNone(cache.get("k1"))

    def test_eviction_on_overflow(self):
        cache = TTLResponseCache(max_entries=2)
        cache.set("a", 1, ttl_seconds=60.0)
        time.sleep(0.01)
        cache.set("b", 2, ttl_seconds=60.0)
        time.sleep(0.01)
        # Third entry should evict the oldest ("a")
        cache.set("c", 3, ttl_seconds=60.0)
        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.get("b"), 2)
        self.assertEqual(cache.get("c"), 3)

    def test_max_entries_floor(self):
        cache = TTLResponseCache(max_entries=0)
        # Should clamp to 1
        cache.set("k", "v", ttl_seconds=60.0)
        self.assertEqual(cache.get("k"), "v")


# ---------------------------------------------------------------------------
# ProductionRuntime – request tracking
# ---------------------------------------------------------------------------

class TestProductionRuntimeRequests(unittest.TestCase):
    def setUp(self):
        self.rt = ProductionRuntime(RuntimeConfig())

    def test_begin_and_end_request(self):
        self.rt.begin_request()
        snap = self.rt.metrics_snapshot()
        self.assertEqual(snap["in_flight"], 1)

        self.rt.end_request(
            method="GET", path="/api/health", status_code=200,
            latency_ms=12.5, request_id="r1", client_id="c1",
        )
        snap = self.rt.metrics_snapshot()
        self.assertEqual(snap["in_flight"], 0)
        self.assertEqual(snap["requests_total"], 1)
        self.assertEqual(snap["errors_total"], 0)
        self.assertAlmostEqual(snap["avg_latency_ms"], 12.5)

    def test_500_counts_as_error(self):
        self.rt.end_request(
            method="POST", path="/api/chat", status_code=500,
            latency_ms=100, request_id="r2", client_id="c2",
            error="Internal Server Error",
        )
        snap = self.rt.metrics_snapshot()
        self.assertEqual(snap["errors_total"], 1)
        self.assertEqual(snap["status_totals"].get("5xx", 0), 1)

    def test_rejected_request(self):
        self.rt.record_rejected_request(
            method="GET", path="/api/predict", status_code=429,
            latency_ms=1.0, request_id="r3", client_id="c3",
            error="rate limited",
        )
        snap = self.rt.metrics_snapshot()
        self.assertEqual(snap["rejected_total"], 1)
        self.assertEqual(snap["requests_total"], 1)

    def test_max_in_flight_seen(self):
        self.rt.begin_request()
        self.rt.begin_request()
        self.rt.begin_request()
        snap = self.rt.metrics_snapshot()
        self.assertEqual(snap["max_in_flight_seen"], 3)
        self.rt.end_request(
            method="GET", path="/", status_code=200,
            latency_ms=1, request_id="r1", client_id="c1",
        )
        snap = self.rt.metrics_snapshot()
        # max_in_flight_seen should remain 3
        self.assertEqual(snap["max_in_flight_seen"], 3)
        self.assertEqual(snap["in_flight"], 2)


# ---------------------------------------------------------------------------
# ProductionRuntime – traces
# ---------------------------------------------------------------------------

class TestProductionRuntimeTraces(unittest.TestCase):
    def test_traces_recorded_in_order(self):
        cfg = RuntimeConfig(trace_buffer_size=25)
        rt = ProductionRuntime(cfg)
        for i in range(5):
            rt.end_request(
                method="GET", path=f"/path/{i}", status_code=200,
                latency_ms=float(i), request_id=f"r{i}", client_id="c",
            )
        traces = rt.recent_traces(limit=10)
        # Most recent first
        self.assertEqual(traces[0]["path"], "/path/4")
        self.assertEqual(traces[-1]["path"], "/path/0")

    def test_trace_buffer_limit(self):
        cfg = RuntimeConfig(trace_buffer_size=25)
        rt = ProductionRuntime(cfg)
        for i in range(30):
            rt.end_request(
                method="GET", path=f"/p/{i}", status_code=200,
                latency_ms=1, request_id=f"r{i}", client_id="c",
            )
        traces = rt.recent_traces(limit=100)
        self.assertLessEqual(len(traces), 25)


# ---------------------------------------------------------------------------
# ProductionRuntime – rate limiting
# ---------------------------------------------------------------------------

class TestProductionRuntimeRateLimiting(unittest.TestCase):
    def test_disabled_when_rpm_zero(self):
        rt = ProductionRuntime(RuntimeConfig(rate_limit_rpm=0))
        allowed, retry = rt.allow_request("client1")
        self.assertTrue(allowed)
        self.assertEqual(retry, 0)

    def test_allows_up_to_limit(self):
        rt = ProductionRuntime(RuntimeConfig(rate_limit_rpm=3))
        now = time.time()
        for _ in range(3):
            allowed, _ = rt.allow_request("c", now=now)
            self.assertTrue(allowed)

        allowed, retry_after = rt.allow_request("c", now=now)
        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)

    def test_window_slides(self):
        rt = ProductionRuntime(RuntimeConfig(rate_limit_rpm=2))
        base = time.time()
        rt.allow_request("c", now=base)
        rt.allow_request("c", now=base + 1.0)
        # At base+1 we are at limit
        allowed, _ = rt.allow_request("c", now=base + 1.0)
        self.assertFalse(allowed)
        # 61 seconds later the first entry slides out
        allowed, _ = rt.allow_request("c", now=base + 61.0)
        self.assertTrue(allowed)

    def test_per_client_isolation(self):
        rt = ProductionRuntime(RuntimeConfig(rate_limit_rpm=1))
        now = time.time()
        a1, _ = rt.allow_request("alice", now=now)
        b1, _ = rt.allow_request("bob", now=now)
        self.assertTrue(a1)
        self.assertTrue(b1)
        a2, _ = rt.allow_request("alice", now=now)
        self.assertFalse(a2)
        b2, _ = rt.allow_request("bob", now=now)
        self.assertFalse(b2)


# ---------------------------------------------------------------------------
# ProductionRuntime – AI failover state machine
# ---------------------------------------------------------------------------

class TestProductionRuntimeFailover(unittest.TestCase):
    def _make_runtime(self, threshold=3, cooldown=10.0, provider="openai", model="gpt-4o"):
        cfg = RuntimeConfig(
            failover_failure_threshold=threshold,
            failover_cooldown_seconds=cooldown,
            failover_provider=provider,
            failover_model=model,
        )
        return ProductionRuntime(cfg)

    def test_failover_not_enabled_without_provider(self):
        rt = ProductionRuntime(RuntimeConfig())
        self.assertFalse(rt.failover_enabled)
        triggered = rt.record_ai_failure("timeout error")
        self.assertFalse(triggered)

    def test_failover_enabled_with_provider(self):
        rt = self._make_runtime()
        self.assertTrue(rt.failover_enabled)

    def test_streak_below_threshold_does_not_trigger(self):
        rt = self._make_runtime(threshold=3)
        rt.record_ai_failure("timeout")
        rt.record_ai_failure("connection error")
        state = rt.failover_state("openai", "gpt-4o")
        self.assertEqual(state["failure_streak"], 2)
        self.assertEqual(state["activations"], 0)

    def test_streak_at_threshold_triggers(self):
        rt = self._make_runtime(threshold=3)
        rt.record_ai_failure("timeout")
        rt.record_ai_failure("timeout")
        triggered = rt.record_ai_failure("timeout")
        self.assertTrue(triggered)

    def test_success_resets_streak(self):
        rt = self._make_runtime(threshold=3)
        rt.record_ai_failure("timeout")
        rt.record_ai_failure("timeout")
        rt.record_ai_success()
        state = rt.failover_state("openai", "gpt-4o")
        self.assertEqual(state["failure_streak"], 0)

    def test_non_matching_error_ignored(self):
        rt = self._make_runtime(threshold=1)
        triggered = rt.record_ai_failure("some random coding error")
        self.assertFalse(triggered)
        state = rt.failover_state("openai", "gpt-4o")
        self.assertEqual(state["failure_streak"], 0)

    def test_cooldown_blocks_repeat_trigger(self):
        rt = self._make_runtime(threshold=1, cooldown=60.0)
        # First trigger
        triggered1 = rt.record_ai_failure("timeout")
        self.assertTrue(triggered1)
        rt.mark_failover_activated("test")
        # Immediately try again — should be blocked by cooldown
        triggered2 = rt.record_ai_failure("timeout")
        self.assertFalse(triggered2)

    def test_mark_failover_activated(self):
        rt = self._make_runtime()
        rt.mark_failover_activated("primary down")
        state = rt.failover_state("openai", "gpt-4o")
        self.assertEqual(state["activations"], 1)
        self.assertEqual(state["last_reason"], "primary down")
        self.assertGreater(state["last_failover_at"], 0)

    def test_mark_failover_activation_failed(self):
        rt = self._make_runtime()
        rt.mark_failover_activation_failed("config error")
        state = rt.failover_state("openai", "gpt-4o")
        self.assertIn("activation_failed", state["last_reason"])

    def test_failover_state_snapshot(self):
        rt = self._make_runtime(provider="anthropic", model="claude-3-5-sonnet")
        state = rt.failover_state("openai", "gpt-4")
        self.assertTrue(state["enabled"])
        self.assertEqual(state["configured_provider"], "anthropic")
        self.assertEqual(state["configured_model"], "claude-3-5-sonnet")
        self.assertEqual(state["active_provider"], "openai")
        self.assertEqual(state["active_model"], "gpt-4")


# ---------------------------------------------------------------------------
# ProductionRuntime – Prometheus text export
# ---------------------------------------------------------------------------

class TestPrometheusExport(unittest.TestCase):
    def test_basic_export(self):
        rt = ProductionRuntime(RuntimeConfig())
        text = rt.prometheus_text(instance_id="node-1", uptime_seconds=123.456)
        self.assertIn("aetheer_requests_total", text)
        self.assertIn("aetheer_errors_total", text)
        self.assertIn("aetheer_uptime_seconds", text)
        self.assertIn('instance="node-1"', text)
        self.assertIn("123.456", text)

    def test_export_after_traffic(self):
        rt = ProductionRuntime(RuntimeConfig())
        rt.end_request(
            method="GET", path="/api/health", status_code=200,
            latency_ms=5, request_id="r1", client_id="c1",
        )
        rt.end_request(
            method="POST", path="/api/chat", status_code=500,
            latency_ms=50, request_id="r2", client_id="c2",
            error="boom",
        )
        text = rt.prometheus_text("test", 10.0)
        self.assertIn("aetheer_requests_total", text)
        # Should include status bucket lines
        self.assertIn("aetheer_http_responses_total", text)

    def test_label_escaping_in_export(self):
        rt = ProductionRuntime(RuntimeConfig())
        text = rt.prometheus_text(instance_id='node"special', uptime_seconds=1.0)
        # Double-quote inside label should be escaped
        self.assertIn('node\\"special', text)


# ---------------------------------------------------------------------------
# ProductionRuntime – top_paths
# ---------------------------------------------------------------------------

class TestTopPaths(unittest.TestCase):
    def test_top_paths_ordering(self):
        rt = ProductionRuntime(RuntimeConfig())
        for _ in range(3):
            rt.end_request(
                method="GET", path="/a", status_code=200,
                latency_ms=10, request_id="r", client_id="c",
            )
        rt.end_request(
            method="GET", path="/b", status_code=200,
            latency_ms=10, request_id="r", client_id="c",
        )
        snap = rt.metrics_snapshot()
        paths = snap["top_paths"]
        self.assertEqual(paths[0]["path"], "/a")
        self.assertEqual(paths[0]["count"], 3)
        self.assertEqual(paths[1]["path"], "/b")
        self.assertEqual(paths[1]["count"], 1)


if __name__ == "__main__":
    unittest.main()
