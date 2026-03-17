import hashlib
import hmac
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from api import meta_webhook_router
    _API_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    meta_webhook_router = None
    _API_IMPORT_ERROR = exc


@unittest.skipIf(_API_IMPORT_ERROR is not None, f"API module deps unavailable: {_API_IMPORT_ERROR}")
class MetaWebhookRouterTests(unittest.TestCase):
    def _client(self) -> TestClient:
        app = FastAPI()
        app.include_router(meta_webhook_router.router)
        return TestClient(app)

    def test_verify_callback_accepts_valid_token(self):
        with patch.dict(os.environ, {"META_WEBHOOK_VERIFY_TOKEN": "verify-123"}, clear=False):
            response = self._client().get(
                "/api/meta/webhook",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "verify-123",
                    "hub.challenge": "challenge-value",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "challenge-value")

    def test_verify_callback_rejects_token_mismatch(self):
        with patch.dict(os.environ, {"META_WEBHOOK_VERIFY_TOKEN": "verify-123"}, clear=False):
            response = self._client().get(
                "/api/meta/webhook",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "wrong-token",
                    "hub.challenge": "challenge-value",
                },
            )

        self.assertEqual(response.status_code, 403)

    def test_event_callback_accepts_unsigned_payload_when_secret_missing(self):
        with patch.dict(os.environ, {"META_APP_SECRET": ""}, clear=False):
            response = self._client().post(
                "/api/meta/webhook",
                json={"object": "page", "entry": [{"id": "1"}]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "EVENT_RECEIVED")

    def test_event_callback_rejects_bad_signature(self):
        body = b'{"object":"page","entry":[{"id":"1"}]}'
        headers = {
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=bad-signature",
        }

        with patch.dict(os.environ, {"META_APP_SECRET": "app-secret-123"}, clear=False):
            response = self._client().post(
                "/api/meta/webhook",
                content=body,
                headers=headers,
            )

        self.assertEqual(response.status_code, 401)

    def test_event_callback_accepts_valid_signature(self):
        body = b'{"object":"page","entry":[{"id":"1"}]}'
        signature = hmac.new(
            b"app-secret-123",
            body,
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Hub-Signature-256": f"sha256={signature}",
        }

        with patch.dict(os.environ, {"META_APP_SECRET": "app-secret-123"}, clear=False):
            response = self._client().post(
                "/api/meta/webhook",
                content=body,
                headers=headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "EVENT_RECEIVED")


if __name__ == "__main__":
    unittest.main()
