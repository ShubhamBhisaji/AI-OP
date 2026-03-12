"""
AgentRegistry — Central store for all active Aether agents.
Supports registration, lookup, listing, and removal of agents.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

_REGISTRY_FILE = Path(__file__).parent / "registry_store.json"


class AgentRegistry:
    """
    Thread-safe in-memory registry with optional JSON persistence.
    """

    def __init__(self, persist: bool = True):
        self._agents: dict[str, BaseAgent] = {}
        self._persist = persist
        if persist and _REGISTRY_FILE.exists():
            self._load()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register(self, agent: BaseAgent) -> None:
        if agent.name in self._agents:
            logger.warning("Agent '%s' is already registered; overwriting.", agent.name)
        self._agents[agent.name] = agent
        logger.debug("Registered agent: %s", agent.name)
        self._save()

    def get(self, name: str) -> BaseAgent | None:
        return self._agents.get(name)

    def remove(self, name: str) -> bool:
        if name in self._agents:
            del self._agents[name]
            self._save()
            logger.info("Removed agent '%s' from registry.", name)
            return True
        return False

    def list_names(self) -> list[str]:
        return list(self._agents.keys())

    def list_all(self) -> list[dict[str, Any]]:
        return [agent.to_dict() for agent in self._agents.values()]

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        if not self._persist:
            return
        # Atomic write: write to .tmp then rename so an interrupted write never
        # leaves the registry file blank or partially written (Bug 2 fix)
        tmp = Path(str(_REGISTRY_FILE) + ".tmp")
        try:
            data = {name: agent.to_dict() for name, agent in self._agents.items()}
            tmp.write_text(json.dumps(data, indent=2))
            os.replace(tmp, _REGISTRY_FILE)
        except OSError as exc:
            logger.error("Failed to persist registry: %s", exc)
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _load(self) -> None:
        try:
            data: dict[str, Any] = json.loads(_REGISTRY_FILE.read_text())
            for name, profile in data.items():
                agent = BaseAgent(
                    name=profile["name"],
                    role=profile["role"],
                    tools=profile.get("tools", []),
                    skills=profile.get("skills", []),
                )
                agent.profile.update(profile)
                self._agents[name] = agent
            logger.info("Loaded %d agent(s) from registry store.", len(self._agents))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to load registry: %s", exc)
