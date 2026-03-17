"""Shared HTTP transport utilities for external service clients."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

import requests

from .errors import APIRequestError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class HTTPResult:
    """Normalized HTTP response object used by integration clients."""

    status_code: int
    headers: dict[str, str]
    body: Any


class HTTPTransport(Protocol):
    """Protocol for pluggable HTTP transports."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
        files: Any = None,
        timeout: int | None = None,
    ) -> HTTPResult:
        ...


class RequestsHTTPTransport:
    """Default HTTP transport implemented with requests.Session."""

    def __init__(
        self,
        *,
        service_name: str,
        session: requests.Session | None = None,
        default_timeout: int = 20,
    ) -> None:
        self._service_name = service_name
        self._session = session or requests.Session()
        self._default_timeout = default_timeout

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
        files: Any = None,
        timeout: int | None = None,
    ) -> HTTPResult:
        request_timeout = timeout if timeout is not None else self._default_timeout

        try:
            response = self._session.request(
                method=method.upper(),
                url=url,
                headers=dict(headers or {}),
                params=dict(params or {}),
                json=json_body,
                data=data,
                files=files,
                timeout=request_timeout,
            )
        except requests.RequestException as exc:
            raise APIRequestError(
                self._service_name,
                f"Request failed: {exc}",
            ) from exc

        parsed_body = _parse_response_body(response)
        return HTTPResult(
            status_code=response.status_code,
            headers={k: v for k, v in response.headers.items()},
            body=parsed_body,
        )


def _parse_response_body(response: requests.Response) -> Any:
    """Best-effort parse into JSON; fallback to text payload."""
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type:
        try:
            return response.json()
        except ValueError:
            logger.warning("Failed to decode JSON response body; returning text")

    text_body = response.text or ""
    if not text_body.strip():
        return ""

    # Some APIs return JSON without the content-type header.
    try:
        return json.loads(text_body)
    except ValueError:
        return text_body
