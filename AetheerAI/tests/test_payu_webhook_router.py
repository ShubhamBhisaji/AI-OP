import hashlib
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
    from api import payu_webhook_router
    _API_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    payu_webhook_router = None
    _API_IMPORT_ERROR = exc


@unittest.skipIf(_API_IMPORT_ERROR is not None, f"API module deps unavailable: {_API_IMPORT_ERROR}")
class PayUWebhookRouterTests(unittest.TestCase):
    @staticmethod
    def _payu_env() -> dict[str, str]:
        return {
            "PAYU_MERCHANT_KEY": "merchant-key",
            "PAYU_MERCHANT_SALT": "merchant-salt",
            "PAYU_BASE_URL": "https://secure.payu.in",
            "PAYU_PAYMENT_PATH": "/_payment",
            "PAYU_POSTSERVICE_PATH": "/merchant/postservice?form=2",
            "PAYU_SUCCESS_URL": "https://example.com/api/payu/success",
            "PAYU_FAILURE_URL": "https://example.com/api/payu/failure",
            "PAYU_TIMEOUT_SECONDS": "20",
        }

    def _client(self) -> TestClient:
        app = FastAPI()
        app.include_router(payu_webhook_router.router)
        return TestClient(app)

    @staticmethod
    def _response_hash(
        *,
        merchant_key: str,
        merchant_salt: str,
        status: str,
        txnid: str,
        amount: float,
        product_info: str,
        first_name: str,
        email: str,
        udf1: str = "",
        udf2: str = "",
        udf3: str = "",
        udf4: str = "",
        udf5: str = "",
    ) -> str:
        sequence = [
            merchant_salt,
            status,
            "",
            "",
            "",
            "",
            "",
            udf5,
            udf4,
            udf3,
            udf2,
            udf1,
            email,
            first_name,
            product_info,
            f"{amount:.2f}",
            txnid,
            merchant_key,
        ]
        return hashlib.sha512("|".join(sequence).encode("utf-8")).hexdigest()

    def test_success_callback_accepts_valid_hash(self):
        payload = {
            "status": "success",
            "txnid": "TXN123456",
            "amount": "299.00",
            "productinfo": "Starter",
            "firstname": "Buyer",
            "email": "buyer@example.com",
        }
        payload["hash"] = self._response_hash(
            merchant_key="merchant-key",
            merchant_salt="merchant-salt",
            status=payload["status"],
            txnid=payload["txnid"],
            amount=float(payload["amount"]),
            product_info=payload["productinfo"],
            first_name=payload["firstname"],
            email=payload["email"],
        )

        with patch.dict(os.environ, self._payu_env(), clear=False):
            response = self._client().post("/api/payu/success", data=payload)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("verified"))
        self.assertEqual(response.json().get("callback"), "success")

    def test_failure_callback_rejects_invalid_hash(self):
        payload = {
            "status": "failure",
            "txnid": "TXN123456",
            "amount": "299.00",
            "productinfo": "Starter",
            "firstname": "Buyer",
            "email": "buyer@example.com",
            "hash": "invalid-hash",
        }

        with patch.dict(os.environ, self._payu_env(), clear=False):
            response = self._client().post("/api/payu/failure", data=payload)

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
