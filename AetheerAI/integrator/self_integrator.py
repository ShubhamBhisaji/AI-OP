"""SelfIntegrator — The engine that makes AetheerAI agents plug themselves
into customer environments.

Flow:
    1. User provides target config (domain, API key, integration type)
    2. SelfIntegrator creates the appropriate connector
    3. Tests connectivity
    4. Attaches the live integration to the agent's runtime
    5. Returns structured result

This is AetheerAI's core differentiator: agents integrate themselves.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_VALID_TYPES = frozenset({"website", "api", "custom"})


@dataclass
class IntegrationResult:
    """Structured result from an integration attempt."""
    status: str = "pending"  # connected | error | disconnected
    integration_type: str = ""
    target: str = ""
    endpoints_discovered: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    connected_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "integration_type": self.integration_type,
            "target": self.target,
            "endpoints_discovered": self.endpoints_discovered,
            "errors": self.errors,
            "connected_at": self.connected_at,
        }


class SelfIntegrator:
    """
    Orchestrates agent self-integration into customer environments.

    Usage
    -----
    integrator = SelfIntegrator(registry)
    result = integrator.integrate("my_agent", {
        "type": "website",
        "domain": "https://myshop.com",
        "api_key": "sk-...",
    })
    """

    def __init__(self, registry: Any) -> None:
        self._registry = registry
        self._integrations: dict[str, dict[str, Any]] = {}  # agent_name → {name → connector}

    def integrate(
        self,
        agent_name: str,
        target_config: dict[str, Any],
    ) -> IntegrationResult:
        """
        Connect an agent to a target environment.

        Parameters
        ----------
        agent_name    : Name of a registered agent.
        target_config : Dict with keys:
            - type: "website" | "api" | "custom"
            - domain / base_url: target URL
            - api_key / credentials: authentication
        """
        result = IntegrationResult()

        # Validate agent exists
        agent = self._registry.get(agent_name)
        if agent is None:
            result.status = "error"
            result.errors.append(f"Agent '{agent_name}' not found in registry.")
            return result

        # Validate config
        integration_type = str(target_config.get("type", "website")).strip().lower()
        if integration_type not in _VALID_TYPES:
            result.status = "error"
            result.errors.append(f"Invalid type '{integration_type}'. Use: {sorted(_VALID_TYPES)}")
            return result

        result.integration_type = integration_type

        try:
            if integration_type == "website":
                connector_result = self._connect_website(target_config)
            elif integration_type == "api":
                connector_result = self._connect_api(target_config)
            else:
                connector_result = self._connect_custom(target_config)

            if connector_result.get("status") == "error":
                result.status = "error"
                result.errors.append(connector_result.get("error", "Unknown error"))
                return result

            # Store the integration
            integration_name = target_config.get("name", integration_type)
            if agent_name not in self._integrations:
                self._integrations[agent_name] = {}
            self._integrations[agent_name][integration_name] = {
                "type": integration_type,
                "config": {k: v for k, v in target_config.items() if k not in ("api_key", "credentials", "password")},
                "connector": connector_result,
                "connected_at": time.time(),
            }

            result.status = "connected"
            result.target = target_config.get("domain") or target_config.get("base_url", "")
            result.endpoints_discovered = connector_result.get("endpoints", [])
            result.connected_at = time.time()

            logger.info(
                "SelfIntegrator: agent '%s' integrated with %s (%s)",
                agent_name, result.target, integration_type,
            )

        except Exception as exc:
            result.status = "error"
            result.errors.append(str(exc))
            logger.error("SelfIntegrator: integration failed for '%s': %s", agent_name, exc)

        return result

    def disconnect(self, agent_name: str, integration_name: str) -> bool:
        """Remove an integration from an agent."""
        agent_integrations = self._integrations.get(agent_name, {})
        if integration_name not in agent_integrations:
            return False
        del agent_integrations[integration_name]
        logger.info("SelfIntegrator: disconnected '%s' from agent '%s'.", integration_name, agent_name)
        return True

    def list_integrations(self, agent_name: str) -> list[dict[str, Any]]:
        """List all active integrations for an agent."""
        agent_integrations = self._integrations.get(agent_name, {})
        return [
            {
                "name": name,
                "type": info.get("type", ""),
                "config": info.get("config", {}),
                "connected_at": info.get("connected_at", 0),
            }
            for name, info in agent_integrations.items()
        ]

    def list_all(self) -> dict[str, list[dict[str, Any]]]:
        """List integrations for all agents."""
        return {name: self.list_integrations(name) for name in self._integrations}

    # ── Connector factories ───────────────────────────────────────────────

    @staticmethod
    def _connect_website(config: dict[str, Any]) -> dict[str, Any]:
        from integrations.website_connector import WebsiteConnector
        connector = WebsiteConnector()
        return connector.connect(
            domain=config.get("domain", ""),
            api_key=config.get("api_key", ""),
            discover=config.get("discover", True),
        )

    @staticmethod
    def _connect_api(config: dict[str, Any]) -> dict[str, Any]:
        from integrations.generic_api import GenericAPIClient
        client = GenericAPIClient()
        return client.connect(
            base_url=config.get("base_url", ""),
            auth_type=config.get("auth_type", "bearer"),
            credentials=config.get("credentials", {}),
        )

    @staticmethod
    def _connect_custom(config: dict[str, Any]) -> dict[str, Any]:
        """Custom integrations — just validate and store config."""
        target = config.get("domain") or config.get("base_url", "")
        if not target:
            return {"status": "error", "error": "Custom integration requires 'domain' or 'base_url'."}
        return {"status": "connected", "target": target, "endpoints": []}
