"""PayU Money wrapper for checkout, payment links, and verification."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import uuid
from typing import Any
from urllib.parse import urlparse

from integrations.base_client import BaseServiceClient
from integrations.config import PayUConfig
from integrations.http import HTTPTransport


class PayUClient(BaseServiceClient):
    """High-level helper around PayU checkout and transaction APIs."""

    service_name = "payu"
    _TXN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{5,63}$")
    _EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

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
        safe_prefix = re.sub(r"[^A-Za-z0-9]", "", prefix or "TXN")[:12] or "TXN"
        return f"{safe_prefix}{uuid.uuid4().hex[:20]}"

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
        self._validate_checkout_fields(
            amount=amount,
            product_info=product_info,
            first_name=first_name,
            email=email,
            transaction_id=transaction_id,
        )
        self._validate_redirect_url(success_url or self.config.success_url, field_name="success_url")
        self._validate_redirect_url(failure_url or self.config.failure_url, field_name="failure_url")

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
        self._validate_transaction_id(transaction_id)

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
        self._validate_checkout_fields(
            amount=amount,
            product_info=product_info,
            first_name=first_name,
            email=email,
            transaction_id=transaction_id,
        )
        self._validate_redirect_url(self.config.success_url, field_name="success_url")
        self._validate_redirect_url(self.config.failure_url, field_name="failure_url")

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
        received = (received_signature or "").strip().lower()
        return bool(received) and hmac.compare_digest(expected, received)

    def verify_payment_response_hash(
        self,
        *,
        status: str,
        txnid: str,
        amount: float,
        product_info: str,
        first_name: str,
        email: str,
        received_hash: str,
        udf1: str = "",
        udf2: str = "",
        udf3: str = "",
        udf4: str = "",
        udf5: str = "",
        additional_charges: str = "",
    ) -> bool:
        """
        Verify the hash returned by PayU success/failure callbacks.

        This helps detect tampered response payloads before marking a payment as final.
        """
        self._validate_checkout_fields(
            amount=amount,
            product_info=product_info,
            first_name=first_name,
            email=email,
            transaction_id=txnid,
        )

        amount_str = f"{amount:.2f}"
        sequence = [
            self.config.merchant_salt,
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
            amount_str,
            txnid,
            self.config.merchant_key,
        ]
        if additional_charges:
            sequence.insert(0, str(additional_charges))

        expected = hashlib.sha512("|".join(sequence).encode("utf-8")).hexdigest()
        received = (received_hash or "").strip().lower()
        return bool(received) and hmac.compare_digest(expected, received)

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

    def _validate_checkout_fields(
        self,
        *,
        amount: float,
        product_info: str,
        first_name: str,
        email: str,
        transaction_id: str | None,
    ) -> None:
        if not isinstance(amount, (int, float)) or not math.isfinite(float(amount)):
            raise ValueError("amount must be a finite numeric value")
        if float(amount) <= 0:
            raise ValueError("amount must be greater than zero")

        if not product_info or len(product_info.strip()) > 255:
            raise ValueError("product_info is required and must be <= 255 characters")
        if not first_name or len(first_name.strip()) > 60:
            raise ValueError("first_name is required and must be <= 60 characters")
        if not self._EMAIL_RE.match((email or "").strip()):
            raise ValueError("email must be a valid email address")

        if transaction_id:
            self._validate_transaction_id(transaction_id)

    def _validate_transaction_id(self, transaction_id: str) -> None:
        value = (transaction_id or "").strip()
        if not self._TXN_ID_RE.match(value):
            raise ValueError(
                "transaction_id must be 6-64 chars and contain only letters, digits, '_' or '-'"
            )

    def _validate_redirect_url(self, url: str, *, field_name: str) -> None:
        parsed = urlparse(url or "")
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"{field_name} must be an absolute http/https URL")
        if not parsed.netloc:
            raise ValueError(f"{field_name} must include a network host")

    def _url(self, path: str) -> str:
        return f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
