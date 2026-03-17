import sys
import unittest
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from integrations.errors import APIRequestError
from integrations.http import RequestsHTTPTransport


class _FakeResponse:
    def __init__(self, status_code=200, *, json_payload=None, text="", headers=None):
        self.status_code = status_code
        self._json_payload = json_payload
        self.text = text
        self.headers = headers or {"Content-Type": "application/json"}

    def json(self):
        if isinstance(self._json_payload, Exception):
            raise self._json_payload
        return self._json_payload


class _FakeSession:
    def __init__(self, side_effects):
        self._side_effects = list(side_effects)
        self.calls = 0

    def request(self, **kwargs):
        self.calls += 1
        if not self._side_effects:
            raise AssertionError("No side effects left")
        effect = self._side_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


class HTTPTransportResilienceTests(unittest.TestCase):
    def test_retries_network_errors_then_succeeds(self):
        session = _FakeSession(
            [
                requests.Timeout("timeout"),
                _FakeResponse(status_code=200, json_payload={"ok": True}),
            ]
        )
        transport = RequestsHTTPTransport(
            service_name="test-service",
            session=session,
            max_retries=2,
            retry_backoff_seconds=0,
        )

        result = transport.request("GET", "https://api.example.com/v1/health")

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.body, {"ok": True})
        self.assertEqual(session.calls, 2)

    def test_retries_retryable_status_code_then_succeeds(self):
        session = _FakeSession(
            [
                _FakeResponse(status_code=503, json_payload={"error": "down"}),
                _FakeResponse(status_code=200, json_payload={"ok": 1}),
            ]
        )
        transport = RequestsHTTPTransport(
            service_name="test-service",
            session=session,
            max_retries=2,
            retry_backoff_seconds=0,
        )

        result = transport.request("POST", "https://api.example.com/v1/work")

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.body, {"ok": 1})
        self.assertEqual(session.calls, 2)

    def test_raises_after_retry_exhaustion(self):
        session = _FakeSession(
            [
                requests.ConnectionError("conn-1"),
                requests.ConnectionError("conn-2"),
            ]
        )
        transport = RequestsHTTPTransport(
            service_name="test-service",
            session=session,
            max_retries=1,
            retry_backoff_seconds=0,
        )

        with self.assertRaises(APIRequestError) as cm:
            transport.request("GET", "https://api.example.com/v1/data")

        self.assertIn("after 2 attempt", str(cm.exception))
        self.assertEqual(session.calls, 2)

    def test_logs_sanitized_url_without_query_string(self):
        session = _FakeSession(
            [
                _FakeResponse(status_code=503, json_payload={"error": "busy"}),
                _FakeResponse(status_code=200, json_payload={"ok": True}),
            ]
        )
        transport = RequestsHTTPTransport(
            service_name="test-service",
            session=session,
            max_retries=1,
            retry_backoff_seconds=0,
        )

        with self.assertLogs("integrations.http", level="WARNING") as logs:
            transport.request("GET", "https://api.example.com/v1/x?token=secret&x=1")

        joined = "\n".join(logs.output)
        self.assertIn("https://api.example.com/v1/x", joined)
        self.assertNotIn("token=secret", joined)


if __name__ == "__main__":
    unittest.main()
