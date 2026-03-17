import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from api import auth as auth_mod
    from api import server as server_mod
    _API_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    auth_mod = None
    server_mod = None
    _API_IMPORT_ERROR = exc

from integrations.config.payu_config import PayUConfig
from integrations.payu_client import PayUClient


@unittest.skipIf(_API_IMPORT_ERROR is not None, f"API module deps unavailable: {_API_IMPORT_ERROR}")
class AuthHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        auth_mod._login_attempts.clear()

    def test_signed_stdlib_token_rejects_tampering(self):
        with patch.object(auth_mod, "_HAS_JOSE", False), patch.object(auth_mod, "_SECRET", "unit-test-secret"):
            token = auth_mod._make_token(user_id=7, username="alice", is_admin=False)
            payload = auth_mod._decode_token(token)

            self.assertEqual(payload["sub"], "7")
            self.assertEqual(payload["un"], "alice")

            tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
            with self.assertRaises(HTTPException):
                auth_mod._decode_token(tampered)

    def test_login_attempts_are_rate_limited(self):
        with patch.object(auth_mod, "_LOGIN_MAX_ATTEMPTS", 2), patch.object(auth_mod, "_LOGIN_WINDOW_SECONDS", 120):
            ok1, _ = auth_mod._consume_login_attempt("alice", "1.2.3.4")
            ok2, _ = auth_mod._consume_login_attempt("alice", "1.2.3.4")
            ok3, retry_after = auth_mod._consume_login_attempt("alice", "1.2.3.4")

            self.assertTrue(ok1)
            self.assertTrue(ok2)
            self.assertFalse(ok3)
            self.assertGreater(retry_after, 0)


@unittest.skipIf(_API_IMPORT_ERROR is not None, f"API module deps unavailable: {_API_IMPORT_ERROR}")
class ApiKeyRBACTests(unittest.TestCase):
    def test_role_aware_key_parsing(self):
        parsed = server_mod._parse_api_keys("reader:key-read,writer:key-write,key-admin")

        self.assertEqual(parsed["key-read"], "reader")
        self.assertEqual(parsed["key-write"], "writer")
        self.assertEqual(parsed["key-admin"], "admin")

    def test_required_role_policy(self):
        self.assertEqual(server_mod._required_role_for("/api/goals", "GET"), "reader")
        self.assertEqual(server_mod._required_role_for("/api/goals", "POST"), "writer")
        self.assertEqual(server_mod._required_role_for("/api/goals/abc", "DELETE"), "admin")
        self.assertTrue(server_mod._role_allows("admin", "writer"))
        self.assertTrue(server_mod._role_allows("writer", "reader"))
        self.assertFalse(server_mod._role_allows("reader", "writer"))


class PayUHardeningTests(unittest.TestCase):
    def _client(self) -> PayUClient:
        cfg = PayUConfig(
            merchant_key="merchant-key",
            merchant_salt="merchant-salt",
            base_url="https://secure.payu.in",
            payment_path="/_payment",
            postservice_path="/merchant/postservice?form=2",
            success_url="https://example.com/pay/success",
            failure_url="https://example.com/pay/failure",
            timeout_seconds=20,
        )
        return PayUClient(config=cfg)

    def test_checkout_rejects_invalid_amount(self):
        client = self._client()
        with self.assertRaises(ValueError):
            client.build_checkout_payload(
                amount=0,
                product_info="Starter",
                first_name="Alice",
                email="alice@example.com",
            )

    def test_webhook_signature_verification_uses_expected_hash(self):
        client = self._client()
        body = '{"status":"success"}'
        sig = hashlib.sha512(f"{body}|{client.config.merchant_salt}".encode("utf-8")).hexdigest()

        self.assertTrue(client.verify_webhook_signature(body=body, received_signature=sig))
        self.assertFalse(client.verify_webhook_signature(body=body, received_signature="bad-signature"))

    def test_payment_response_hash_validation(self):
        client = self._client()
        amount = 299.0
        txnid = "TXN123456"
        sequence = [
            client.config.merchant_salt,
            "success",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "buyer@example.com",
            "Buyer",
            "Starter",
            f"{amount:.2f}",
            txnid,
            client.config.merchant_key,
        ]
        received_hash = hashlib.sha512("|".join(sequence).encode("utf-8")).hexdigest()

        self.assertTrue(
            client.verify_payment_response_hash(
                status="success",
                txnid=txnid,
                amount=amount,
                product_info="Starter",
                first_name="Buyer",
                email="buyer@example.com",
                received_hash=received_hash,
            )
        )


if __name__ == "__main__":
    unittest.main()