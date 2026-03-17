"""PayU Money wrapper for checkout, payment links, and verification."""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from integrations.base_client import BaseServiceClient
from integrations.config import PayUConfig
from integrations.http import HTTPTransport


class PayUClient(BaseServiceClient):
    """High-level helper around PayU checkout and transaction APIs."""

    service_name = "payu"

    def __init__(
        self,
        config: PayUConfig | None = None,
        *,
        transport: HTTPTransport | None = None,
    ) -> None:
        self.config = config or PayUConfig.from_env()
        super().__init__(
            transport=transport,
            timeout_seconds=self.config.timeout_seconds,
        )

    def generate_transaction_id(self, prefix: str = "TXN") -> str:
        return f"{prefix}{uuid.uuid4().hex[:20]}"

    def build_checkout_payload(
        self,
        *,
        amount: float,
        product_info: str,
        first_name: str,
        email: str,
        phone: str = "",
        transaction_id: str | None = None,
        success_url: str | None = None,
        failure_url: str | None = None,
        udf1: str = "",
        udf2: str = "",
        udf3: str = "",
        udf4: str = "",
        udf5: str = "",
    ) -> dict[str, Any]:
        txnid = transaction_id or self.generate_transaction_id()
        amount_str = f"{amount:.2f}"

        hash_value = self._payment_hash(
            txnid=txnid,
            amount=amount_str,
            product_info=product_info,
            first_name=first_name,
            email=email,
            udf1=udf1,
            udf2=udf2,
            udf3=udf3,
            udf4=udf4,
            udf5=udf5,
        )

        form_fields: dict[str, Any] = {
            "key": self.config.merchant_key,
            "txnid": txnid,
            "amount": amount_str,
            "productinfo": product_info,
            "firstname": first_name,
            "email": email,
            "phone": phone,
            "surl": success_url or self.config.success_url,
            "furl": failure_url or self.config.failure_url,
            "udf1": udf1,
            "udf2": udf2,
            "udf3": udf3,
            "udf4": udf4,
            "udf5": udf5,
            "service_provider": "payu_paisa",
            "hash": hash_value,
        }

        return {
            "checkout_url": self._url(self.config.payment_path),
            "transaction_id": txnid,
            "form_fields": form_fields,
        }

    def verify_transaction(self, *, transaction_id: str) -> Any:
        command = "verify_payment"
        hash_value = self._command_hash(command=command, var1=transaction_id)

        payload = {
            "key": self.config.merchant_key,
            "command": command,
            "var1": transaction_id,
            "hash": hash_value,
        }

        return self._request(
            "POST",
            self._url(self.config.postservice_path),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=payload,
            expected_statuses=(200,),
            error_context="PayU transaction verification failed",
        )

    def create_payment_link(
        self,
        *,
        amount: float,
        product_info: str,
        first_name: str,
        email: str,
        phone: str = "",
        transaction_id: str | None = None,
        notes: dict[str, Any] | None = None,
    ) -> Any:
        """
        Create a PayU payment link using postservice command API.

        This follows PayU's command-based API style and can be adapted
        if your account uses a different command endpoint.
        """
        txnid = transaction_id or self.generate_transaction_id(prefix="LNK")
        request_payload = {
            "txnid": txnid,
            "amount": f"{amount:.2f}",
            "productinfo": product_info,
            "firstname": first_name,
            "email": email,
            "phone": phone,
            "surl": self.config.success_url,
            "furl": self.config.failure_url,
            "notes": notes or {},
        }

        command = "create_payment_link"
        var1 = json.dumps(request_payload, separators=(",", ":"))
        hash_value = self._command_hash(command=command, var1=var1)

        payload = {
            "key": self.config.merchant_key,
            "command": command,
            "var1": var1,
            "hash": hash_value,
        }

        return self._request(
            "POST",
            self._url(self.config.postservice_path),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=payload,
            expected_statuses=(200,),
            error_context="PayU payment link creation failed",
        )

    def verify_webhook_signature(self, *, body: str, received_signature: str) -> bool:
        expected = hashlib.sha512(
            f"{body}|{self.config.merchant_salt}".encode("utf-8")
        ).hexdigest()
        return expected == (received_signature or "").strip()

    def _payment_hash(
        self,
        *,
        txnid: str,
        amount: str,
        product_info: str,
        first_name: str,
        email: str,
        udf1: str,
        udf2: str,
        udf3: str,
        udf4: str,
        udf5: str,
    ) -> str:
        sequence = [
            self.config.merchant_key,
            txnid,
            amount,
            product_info,
            first_name,
            email,
            udf1,
            udf2,
            udf3,
            udf4,
            udf5,
            "",
            "",
            "",
            "",
            "",
            self.config.merchant_salt,
        ]
        return hashlib.sha512("|".join(sequence).encode("utf-8")).hexdigest()

    def _command_hash(self, *, command: str, var1: str) -> str:
        hash_input = (
            f"{self.config.merchant_key}|{command}|{var1}|{self.config.merchant_salt}"
        )
        return hashlib.sha512(hash_input.encode("utf-8")).hexdigest()

    def _url(self, path: str) -> str:
        return f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
