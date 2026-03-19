"""GenericAPIClient — Universal REST API connector for AetheerAI agents.

Allows agents to connect to any REST API with configurable authentication
(Bearer token, API key header, or Basic auth) and make arbitrary calls.
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from typing import Any, Mapping

from .base_client import BaseServiceClient

logger = logging.getLogger(__name__)

_VALID_AUTH_TYPES = frozenset({"bearer", "api_key", "basic", "none"})


@dataclass
class APIConnectionState:
    base_url: str = ""
    auth_type: str = "none"
    connected: bool = False
    connected_at: float = 0.0


class GenericAPIClient(BaseServiceClient):
    """Connect an AetheerAI agent to any REST API."""

    service_name = "generic-api"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._state = APIConnectionState()
        self._auth_headers: dict[str, str] = {}

    @property
    def connected(self) -> bool:
        return self._state.connected

    def connect(
        self,
        base_url: str,
        auth_type: str = "bearer",
        credentials: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Connect to a REST API.

        Parameters
        ----------
        base_url    : API root (e.g. "https://api.example.com/v1")
        auth_type   : "bearer", "api_key", "basic", or "none"
        credentials : Auth details. Keys depend on auth_type:
                      - bearer:  {"token": "..."}
                      - api_key: {"header": "X-API-Key", "key": "..."}
                      - basic:   {"username": "...", "password": "..."}
                      - none:    {} or None
        """
        base_url = base_url.strip().rstrip("/")
        if not base_url:
            return {"status": "error", "error": "base_url is required."}

        auth_type = auth_type.strip().lower()
        if auth_type not in _VALID_AUTH_TYPES:
            return {"status": "error", "error": f"Invalid auth_type '{auth_type}'. Use: {sorted(_VALID_AUTH_TYPES)}"}

        credentials = credentials or {}

        # Build auth headers
        self._auth_headers = {}
        if auth_type == "bearer":
            token = credentials.get("token", "")
            if not token:
                return {"status": "error", "error": "Bearer auth requires 'token' in credentials."}
            self._auth_headers["Authorization"] = f"Bearer {token}"

        elif auth_type == "api_key":
            header_name = credentials.get("header", "X-API-Key")
            key = credentials.get("key", "")
            if not key:
                return {"status": "error", "error": "API key auth requires 'key' in credentials."}
            self._auth_headers[header_name] = key

        elif auth_type == "basic":
            username = credentials.get("username", "")
            password = credentials.get("password", "")
            if not username:
                return {"status": "error", "error": "Basic auth requires 'username' in credentials."}
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
            self._auth_headers["Authorization"] = f"Basic {encoded}"

        # Test connection
        try:
            self._request(
                "HEAD", base_url,
                headers=self._auth_headers,
                expected_statuses=(200, 204, 301, 302, 304, 401, 403, 404, 405),
                error_context="API connectivity test",
            )
        except Exception as exc:
            logger.warning("GenericAPIClient: failed to reach %s: %s", base_url, exc)
            return {"status": "error", "error": f"Cannot reach {base_url}: {exc}"}

        self._state = APIConnectionState(
            base_url=base_url,
            auth_type=auth_type,
            connected=True,
            connected_at=time.time(),
        )
        logger.info("GenericAPIClient: connected to %s (auth=%s)", base_url, auth_type)
        return {"status": "connected", "base_url": base_url, "auth_type": auth_type}

    def call(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Any:
        """Make an authenticated API call."""
        if not self._state.connected:
            raise RuntimeError("Not connected. Call connect() first.")

        url = f"{self._state.base_url}/{path.lstrip('/')}"
        headers = {**self._auth_headers, **(extra_headers or {})}

        return self._request(
            method, url,
            headers=headers,
            params=params,
            json_body=json_body,
            expected_statuses=(200, 201, 204),
            error_context=f"{method.upper()} {path}",
        )

    def test_connection(self) -> dict[str, Any]:
        """Verify the connection is still valid."""
        if not self._state.connected:
            return {"status": "disconnected"}
        try:
            self._request(
                "HEAD", self._state.base_url,
                headers=self._auth_headers,
                expected_statuses=(200, 204, 301, 302, 304, 401, 403, 404, 405),
                error_context="Connection test",
            )
            return {"status": "healthy", "base_url": self._state.base_url}
        except Exception as exc:
            return {"status": "unhealthy", "error": str(exc)}

    def disconnect(self) -> None:
        """Clear connection state and credentials."""
        self._state = APIConnectionState()
        self._auth_headers.clear()
        logger.info("GenericAPIClient: disconnected.")
