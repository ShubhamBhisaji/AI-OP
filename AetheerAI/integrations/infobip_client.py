"""Infobip wrapper for WhatsApp, Email, and notification delivery."""
from __future__ import annotations

from typing import Any

from integrations.base_client import BaseServiceClient
from integrations.config import InfobipConfig
from integrations.errors import ConfigurationError
from integrations.http import HTTPTransport


class InfobipClient(BaseServiceClient):
    """High-level messaging client for Infobip channels."""

    service_name = "infobip"

    def __init__(
        self,
        config: InfobipConfig | None = None,
        *,
        transport: HTTPTransport | None = None,
    ) -> None:
        self.config = config or InfobipConfig.from_env()
        super().__init__(
            transport=transport,
            timeout_seconds=self.config.timeout_seconds,
        )

    def send_whatsapp_text(
        self,
        *,
        to_number: str,
        text: str,
        sender: str | None = None,
    ) -> Any:
        from_number = sender or self.config.whatsapp_sender
        if not from_number:
            raise ConfigurationError(
                "INFOBIP_WHATSAPP_SENDER is required for WhatsApp messages"
            )

        payload = {
            "from": from_number,
            "to": to_number,
            "content": {"text": text},
        }

        return self._request(
            "POST",
            self._url("/whatsapp/1/message/text"),
            headers=self._headers(json_content=True),
            json_body=payload,
            expected_statuses=(200, 202),
            error_context="Infobip WhatsApp send failed",
        )

    def send_email(
        self,
        *,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str = "",
        sender: str | None = None,
    ) -> Any:
        from_email = sender or self.config.email_sender
        if not from_email:
            raise ConfigurationError(
                "INFOBIP_EMAIL_SENDER is required for email delivery"
            )

        # /email/3/send expects multipart/form-data fields (not JSON).
        multipart_fields: list[tuple[str, tuple[None, str]]] = [
            ("from", (None, from_email)),
            ("to", (None, to_email)),
            ("subject", (None, subject)),
            ("text", (None, text_body)),
        ]
        if html_body:
            multipart_fields.append(("html", (None, html_body)))

        return self._request(
            "POST",
            self._url("/email/3/send"),
            headers=self._headers(json_content=False),
            files=multipart_fields,
            expected_statuses=(200, 202),
            error_context="Infobip email send failed",
        )

    def send_notification(
        self,
        *,
        channel: str,
        destination: str,
        message: str,
        subject: str = "AetheerAI Notification",
    ) -> Any:
        """Unified notification helper for channel-based sends."""
        ch = (channel or "").strip().lower()
        if ch == "whatsapp":
            return self.send_whatsapp_text(to_number=destination, text=message)
        if ch == "email":
            return self.send_email(
                to_email=destination,
                subject=subject,
                text_body=message,
            )

        raise ConfigurationError(
            "Unsupported channel. Use one of: whatsapp, email"
        )

    def get_account_balance(self) -> Any:
        return self._request(
            "GET",
            self._url("/account/1/balance"),
            headers=self._headers(json_content=False),
            expected_statuses=(200,),
            error_context="Infobip account balance fetch failed",
        )

    def _url(self, path: str) -> str:
        return f"{self.config.base_url.rstrip('/')}{path}"

    def _headers(self, *, json_content: bool) -> dict[str, str]:
        headers = {
            "Authorization": f"App {self.config.api_key}",
            "Accept": "application/json",
        }
        if json_content:
            headers["Content-Type"] = "application/json"
        return headers
