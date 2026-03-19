"""Base service client with consistent HTTP and error handling."""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .errors import APIRequestError, AuthenticationError
from .http import HTTPResult, HTTPTransport, RequestsHTTPTransport


_DEFAULT_TRANSPORT_FACTORY = None


def set_default_transport_factory(factory) -> None:
    """Register a process-wide transport factory used by service clients."""
    global _DEFAULT_TRANSPORT_FACTORY
    _DEFAULT_TRANSPORT_FACTORY = factory


def clear_default_transport_factory() -> None:
    """Clear the process-wide transport factory override."""
    global _DEFAULT_TRANSPORT_FACTORY
    _DEFAULT_TRANSPORT_FACTORY = None


def build_default_transport(service_name: str, timeout_seconds: int) -> HTTPTransport:
    """Resolve the transport that should back a service client."""
    if _DEFAULT_TRANSPORT_FACTORY is not None:
        try:
            transport = _DEFAULT_TRANSPORT_FACTORY(
                service_name=service_name,
                timeout_seconds=timeout_seconds,
            )
        except TypeError:
            transport = _DEFAULT_TRANSPORT_FACTORY(service_name, timeout_seconds)
        if transport is not None:
            return transport

    return RequestsHTTPTransport(
        service_name=service_name,
        default_timeout=timeout_seconds,
    )


class BaseServiceClient:
    """Common functionality used by all integration clients."""

    service_name = "external-service"

    def __init__(
        self,
        *,
        transport: HTTPTransport | None = None,
        timeout_seconds: int = 20,
    ) -> None:
        self._log = logging.getLogger(f"integrations.{self.service_name}")
        self._timeout_seconds = timeout_seconds
        self._transport = transport or build_default_transport(
            service_name=self.service_name,
            timeout_seconds=timeout_seconds,
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
        files: Any = None,
        expected_statuses: Sequence[int] = (200,),
        error_context: str = "API call failed",
    ) -> Any:
        self._log.debug(
            "HTTP request %s %s",
            method.upper(),
            _sanitize_url(url),
        )

        response: HTTPResult = self._transport.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json_body=json_body,
            data=data,
            files=files,
            timeout=self._timeout_seconds,
        )

        if response.status_code in (401, 403):
            self._log.warning(
                "Authentication rejected for %s: status=%s",
                _sanitize_url(url),
                response.status_code,
            )
            raise AuthenticationError(
                (
                    f"[{self.service_name}] Authentication failed. "
                    "Verify API keys/tokens and permissions."
                )
            )

        if response.status_code not in expected_statuses:
            self._log.warning(
                "%s: status=%s endpoint=%s",
                error_context,
                response.status_code,
                _sanitize_url(url),
            )
            raise APIRequestError(
                self.service_name,
                error_context,
                status_code=response.status_code,
                response_body=_truncate_response_payload(response.body),
            )

        self._log.debug(
            "HTTP response status=%s endpoint=%s",
            response.status_code,
            _sanitize_url(url),
        )

        if response.status_code == 204 or response.body == "":
            return {}

        return response.body


def _truncate_response_payload(payload: Any, *, max_len: int = 500) -> Any:
    if isinstance(payload, str):
        if len(payload) > max_len:
            return payload[:max_len] + "..."
        return payload
    return payload


def _sanitize_url(url: str) -> str:
    """Drop query params/fragments to avoid logging tokens or secrets."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
