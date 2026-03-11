"""
TeamManager — Create, persist, and manage named teams of agents.
Teams are persisted to registry/teams_store.json.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_STORE = Path(__file__).parent.parent / "registry" / "teams_store.json"


class TeamManager:
    """
    Manages named teams of agents.

    A team is simply a named list of agent names.  Teams are persisted
    to registry/teams_store.json alongside the agent registry.
    """

    def __init__(self, registry) -> None:
        self.registry = registry
        self._teams: dict[str, list[str]] = {}   # team_name -> [agent_names]
        self._load()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_team(self, name: str, agent_names: list[str]) -> dict:
        """Create a new named team.  Validates all agents exist."""
        if name in self._teams:
            return {"error": f"Team '{name}' already exists.  Use add_to_team to extend it."}
        invalid = [a for a in agent_names if self.registry.get(a) is None]
        if invalid:
            return {"error": f"Agents not found: {', '.join(invalid)}"}
        self._teams[name] = list(dict.fromkeys(agent_names))   # dedupe, preserve order
        self._save()
        return {"team": name, "members": list(self._teams[name])}

    def get_team(self, name: str) -> list[str] | None:
        """Return the list of agent names for a team, or None if not found."""
        return self._teams.get(name)

    def delete_team(self, name: str) -> bool:
        """Delete a team by name (agents themselves are unaffected)."""
        if name not in self._teams:
            return False
        del self._teams[name]
        self._save()
        return True

    def add_member(self, team: str, agent: str) -> dict:
        """Add an agent to an existing team."""
        if team not in self._teams:
            return {"error": f"Team '{team}' not found."}
        if self.registry.get(agent) is None:
            return {"error": f"Agent '{agent}' not found."}
        if agent not in self._teams[team]:
            self._teams[team].append(agent)
            self._save()
        return {"team": team, "members": list(self._teams[team])}

    def remove_member(self, team: str, agent: str) -> dict:
        """Remove an agent from a team."""
        if team not in self._teams:
            return {"error": f"Team '{team}' not found."}
        if agent not in self._teams[team]:
            return {"error": f"Agent '{agent}' is not a member of team '{team}'."}
        self._teams[team].remove(agent)
        self._save()
        return {"team": team, "members": list(self._teams[team])}

    def list_teams(self) -> list[str]:
        """Return all team names."""
        return list(self._teams.keys())

    def list_all(self) -> dict[str, list[str]]:
        """Return the full teams mapping (copy)."""
        return {k: list(v) for k, v in self._teams.items()}

    def resolve_agents(self, team_or_agents: str) -> list[str]:
        """
        Resolve a comma-separated list of agent names OR a team name.
        Returns the list of agent names, or raises ValueError if empty/invalid.
        """
        # Try as a team name first
        if team := self._teams.get(team_or_agents):
            return list(team)
        # Otherwise treat as comma-separated agents
        names = [n.strip() for n in team_or_agents.split(",") if n.strip()]
        if not names:
            raise ValueError("No agents specified.")
        return names

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        _STORE.write_text(json.dumps(self._teams, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if _STORE.exists():
            try:
                data = json.loads(_STORE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._teams = data
                    logger.info("TeamManager: loaded %d team(s).", len(self._teams))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Could not load teams store: %s", e)
