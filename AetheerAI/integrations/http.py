"""Shared HTTP transport utilities for external service clients."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit, urlunsplit

import requests

from .errors import APIRequestError

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


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
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.4,
        retryable_status_codes: set[int] | None = None,
    ) -> None:
        self._service_name = service_name
        self._session = session or requests.Session()
        self._default_timeout = default_timeout
        self._max_retries = max(0, int(max_retries))
        self._retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self._retryable_status_codes = set(retryable_status_codes or _RETRYABLE_STATUS_CODES)

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
        sanitized_url = _sanitize_url(url)
        total_attempts = 1 + self._max_retries
        normalized_method = method.upper()

        for attempt in range(1, total_attempts + 1):
            started = time.monotonic()
            try:
                response = self._session.request(
                    method=normalized_method,
                    url=url,
                    headers=dict(headers or {}),
                    params=dict(params or {}),
                    json=json_body,
                    data=data,
                    files=files,
                    timeout=request_timeout,
                )
            except requests.RequestException as exc:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                will_retry = attempt < total_attempts
                logger.warning(
                    "%s transport error: method=%s endpoint=%s attempt=%d/%d timeout=%ss elapsed_ms=%d retry=%s error=%s",
                    self._service_name,
                    normalized_method,
                    sanitized_url,
                    attempt,
                    total_attempts,
                    request_timeout,
                    elapsed_ms,
                    will_retry,
                    exc,
                )
                if will_retry:
                    self._sleep_before_retry(attempt)
                    continue
                raise APIRequestError(
                    self._service_name,
                    f"Request failed after {attempt} attempt(s): {exc}",
                ) from exc

            parsed_body = _parse_response_body(response)
            elapsed_ms = int((time.monotonic() - started) * 1000)

            if (
                response.status_code in self._retryable_status_codes
                and attempt < total_attempts
            ):
                logger.warning(
                    "%s transient status: method=%s endpoint=%s status=%s attempt=%d/%d elapsed_ms=%d retry=true",
                    self._service_name,
                    normalized_method,
                    sanitized_url,
                    response.status_code,
                    attempt,
                    total_attempts,
                    elapsed_ms,
                )
                self._sleep_before_retry(attempt)
                continue

            logger.debug(
                "%s request complete: method=%s endpoint=%s status=%s attempt=%d/%d elapsed_ms=%d",
                self._service_name,
                normalized_method,
                sanitized_url,
                response.status_code,
                attempt,
                total_attempts,
                elapsed_ms,
            )

            return HTTPResult(
                status_code=response.status_code,
                headers={k: v for k, v in response.headers.items()},
                body=parsed_body,
            )

        raise APIRequestError(self._service_name, "Request failed after retry exhaustion")

    def _sleep_before_retry(self, attempt: int) -> None:
        delay_seconds = min(self._retry_backoff_seconds * (2 ** (attempt - 1)), 5.0)
        if delay_seconds > 0:
            time.sleep(delay_seconds)


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


def _sanitize_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
