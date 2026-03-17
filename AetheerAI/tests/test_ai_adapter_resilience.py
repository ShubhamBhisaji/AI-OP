import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.ai_adapter import AIAdapter


class AIAdapterResilienceTests(unittest.TestCase):
    def _make_adapter(self) -> AIAdapter:
        return AIAdapter(provider="openai", model="gpt-4o")

    def test_failover_uses_secondary_provider_when_primary_fails(self):
        with patch.dict(
            os.environ,
            {
                "AETHEERAI_PROVIDER_FAILOVER": "1",
                "AETHEERAI_PROVIDER_FAILOVER_CHAIN": "ollama,github",
            },
            clear=False,
        ):
            adapter = self._make_adapter()
            calls: list[str] = []

            def fail_openai(messages, model_override=None, **kwargs):
                calls.append("openai")
                raise RuntimeError("openai unavailable")

            def ok_ollama(messages, model_override=None, **kwargs):
                calls.append("ollama")
                return "fallback-ok"

            adapter._chat_openai = fail_openai
            adapter._chat_ollama = ok_ollama

            out = adapter.chat([{"role": "user", "content": "hello"}])
            self.assertEqual(out, "fallback-ok")
            self.assertEqual(calls, ["openai", "ollama"])

    def test_non_retryable_errors_do_not_failover(self):
        with patch.dict(
            os.environ,
            {
                "AETHEERAI_PROVIDER_FAILOVER": "1",
                "AETHEERAI_PROVIDER_FAILOVER_CHAIN": "ollama",
            },
            clear=False,
        ):
            adapter = self._make_adapter()
            calls: list[str] = []

            def fail_openai(messages, model_override=None, **kwargs):
                calls.append("openai")
                raise TypeError("coding bug")

            def ok_ollama(messages, model_override=None, **kwargs):
                calls.append("ollama")
                return "should-not-run"

            adapter._chat_openai = fail_openai
            adapter._chat_ollama = ok_ollama

            with self.assertRaises(TypeError):
                adapter.chat([{"role": "user", "content": "hello"}])

            self.assertEqual(calls, ["openai"])

    def test_circuit_breaker_skips_failing_provider_during_cooldown(self):
        with patch.dict(
            os.environ,
            {
                "AETHEERAI_PROVIDER_FAILOVER": "1",
                "AETHEERAI_PROVIDER_FAILOVER_CHAIN": "ollama",
                "AETHEERAI_PROVIDER_FAILURE_THRESHOLD": "1",
                "AETHEERAI_PROVIDER_FAILURE_COOLDOWN_SECONDS": "120",
            },
            clear=False,
        ):
            adapter = self._make_adapter()
            calls = {"openai": 0, "ollama": 0}

            def fail_openai(messages, model_override=None, **kwargs):
                calls["openai"] += 1
                raise RuntimeError("primary down")

            def ok_ollama(messages, model_override=None, **kwargs):
                calls["ollama"] += 1
                return "ok"

            adapter._chat_openai = fail_openai
            adapter._chat_ollama = ok_ollama

            first = adapter.chat([{"role": "user", "content": "first"}])
            second = adapter.chat([{"role": "user", "content": "second"}])

            self.assertEqual(first, "ok")
            self.assertEqual(second, "ok")
            self.assertEqual(calls["openai"], 1)
            self.assertEqual(calls["ollama"], 2)

            health = adapter.provider_health()
            self.assertTrue(health["openai"]["circuit_open"])


if __name__ == "__main__":
    unittest.main()
