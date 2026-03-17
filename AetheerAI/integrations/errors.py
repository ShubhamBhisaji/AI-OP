"""Custom exception types for external service integrations."""
from __future__ import annotations

from typing import Any


class IntegrationError(RuntimeError):
    """Base class for all integration errors."""


class ConfigurationError(IntegrationError):
    """Raised when required integration configuration is missing or invalid."""


class AuthenticationError(IntegrationError):
    """Raised when credentials are rejected by an external service."""


class APIRequestError(IntegrationError):
    """Raised for failed HTTP/API calls to external services."""

    def __init__(
        self,
        service: str,
        message: str,
        *,
        status_code: int | None = None,
        response_body: Any = None,
    ) -> None:
        self.service = service
        self.status_code = status_code
        self.response_body = response_body

        details = f"[{service}] {message}"
        if status_code is not None:
            details = f"{details} (status={status_code})"

        super().__init__(details)
