"""WebsiteConnector — Generic website integration client for AetheerAI agents.

Allows an agent to connect to any website/web application, validate access,
discover available API endpoints, and perform health checks.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from .base_client import BaseServiceClient

logger = logging.getLogger(__name__)

# Common endpoint paths to probe during discovery
_DISCOVERY_PATHS: list[tuple[str, str]] = [
    ("/api", "REST API root"),
    ("/api/v1", "REST API v1"),
    ("/api/v2", "REST API v2"),
    ("/wp-json/wp/v2", "WordPress REST API"),
    ("/graphql", "GraphQL endpoint"),
    ("/health", "Health check"),
    ("/.well-known/openid-configuration", "OpenID Connect"),
    ("/sitemap.xml", "Sitemap"),
    ("/robots.txt", "Robots.txt"),
]


@dataclass
class ConnectionState:
    domain: str = ""
    base_url: str = ""
    api_key: str = ""
    connected: bool = False
    connected_at: float = 0.0
    endpoints_discovered: list[dict[str, str]] = field(default_factory=list)


class WebsiteConnector(BaseServiceClient):
    """Connect an AetheerAI agent to any website or web application."""

    service_name = "website"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._state = ConnectionState()

    @property
    def connected(self) -> bool:
        return self._state.connected

    def connect(
        self,
        domain: str,
        api_key: str = "",
        *,
        verify_ssl: bool = True,
        discover: bool = True,
    ) -> dict[str, Any]:
        """Validate domain access, store credentials, optionally discover endpoints."""
        domain = domain.strip().rstrip("/")
        if not domain:
            return {"status": "error", "error": "Domain is required."}

        # Normalize to full URL
        if not domain.startswith(("http://", "https://")):
            domain = f"https://{domain}"

        # Test connectivity with a HEAD request
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            self._request(
                "HEAD", domain,
                headers=headers,
                expected_statuses=(200, 301, 302, 304, 403, 405),
                error_context="Website connectivity test",
            )
        except Exception as exc:
            logger.warning("WebsiteConnector: failed to reach %s: %s", domain, exc)
            return {"status": "error", "error": f"Cannot reach {domain}: {exc}"}

        self._state = ConnectionState(
            domain=domain,
            base_url=domain,
            api_key=api_key,
            connected=True,
            connected_at=time.time(),
        )
        logger.info("WebsiteConnector: connected to %s", domain)

        result: dict[str, Any] = {"status": "connected", "domain": domain}

        if discover:
            endpoints = self.discover_endpoints()
            self._state.endpoints_discovered = endpoints
            result["endpoints"] = endpoints

        return result

    def discover_endpoints(self) -> list[dict[str, str]]:
        """Probe common API endpoint paths and return those that respond."""
        if not self._state.connected:
            return []

        found: list[dict[str, str]] = []
        headers: dict[str, str] = {}
        if self._state.api_key:
            headers["Authorization"] = f"Bearer {self._state.api_key}"

        for path, description in _DISCOVERY_PATHS:
            url = urljoin(self._state.base_url + "/", path.lstrip("/"))
            try:
                self._request(
                    "HEAD", url,
                    headers=headers,
                    expected_statuses=(200, 301, 302, 304),
                    error_context=f"Discover {path}",
                )
                found.append({"path": path, "description": description, "status": "found"})
                logger.debug("WebsiteConnector: discovered %s at %s", description, url)
            except Exception:
                pass  # Endpoint not available — skip silently

        return found

    def health_check(self) -> dict[str, Any]:
        """Ping the connected domain and return status."""
        if not self._state.connected:
            return {"status": "disconnected"}

        try:
            self._request(
                "HEAD", self._state.base_url,
                expected_statuses=(200, 301, 302, 304, 403, 405),
                error_context="Health check",
            )
            return {"status": "healthy", "domain": self._state.domain}
        except Exception as exc:
            return {"status": "unhealthy", "domain": self._state.domain, "error": str(exc)}

    def disconnect(self) -> None:
        """Clear connection state."""
        self._state = ConnectionState()
        logger.info("WebsiteConnector: disconnected.")

    def get_state(self) -> dict[str, Any]:
        """Return current connection state (safe — no credentials exposed)."""
        return {
            "domain": self._state.domain,
            "connected": self._state.connected,
            "connected_at": self._state.connected_at,
            "endpoints": self._state.endpoints_discovered,
        }
