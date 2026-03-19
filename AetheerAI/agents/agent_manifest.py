"""agent_manifest.py — Formal runtime manifest for every AetheerAI agent.

The manifest is the single human- and machine-readable description that
the runtime loads to construct an agent's full behaviour without touching
Python class definitions.

Schema (agent_manifest.json)
-----------------------------
{
  "name": "Ecommerce Support Agent",
  "version": "1.0",
  "purpose": "Customer support automation for an online store",
  "skills": ["faq", "order_lookup", "refunds"],
  "integrations": ["shopify", "email"],
  "permissions": {
    "refund_limit": 5000,
    "data_access": "orders_only",
    "allowed_apis": ["shopify", "sendgrid"],
    "rate_limits": {"refund": 20, "email": 100},
    "restricted_commands": ["delete_customer", "export_all_data"],
    "escalation_triggers": ["refund > 5000", "customer_angry"]
  },
  "knowledge": {
    "documents": ["knowledge/documents/faq.txt"],
    "config": "knowledge/config.json"
  },
  "runtime": {
    "permission_level": 2,
    "model": "gpt-4o",
    "provider": "openai",
    "memory_enabled": true,
    "goal_tracking": true
  }
}

Usage
-----
manifest = AgentManifest.from_file("agent_manifest.json")
errors = manifest.validate()
profile_dict = manifest.to_agent_kwargs()
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Default manifest template ──────────────────────────────────────────────

_MANIFEST_DEFAULTS: dict[str, Any] = {
    "version": "1.0",
    "skills": [],
    "integrations": [],
    "permissions": {
        "refund_limit": 0,
        "data_access": "read_only",
        "allowed_apis": [],
        "rate_limits": {},
        "restricted_commands": [],
        "escalation_triggers": [],
    },
    "knowledge": {
        "documents": [],
        "config": "knowledge/config.json",
    },
    "runtime": {
        "permission_level": 1,
        "model": "",
        "provider": "",
        "memory_enabled": True,
        "goal_tracking": True,
    },
}


# ── Manifest dataclass ─────────────────────────────────────────────────────

@dataclass
class AgentManifest:
    """
    Structured, serialisable agent manifest.

    Runtime loads this to construct agent behaviour — no hard-coded classes.
    """

    name: str
    purpose: str
    version: str = "1.0"
    skills: list[str] = field(default_factory=list)
    integrations: list[str] = field(default_factory=list)
    permissions: dict[str, Any] = field(default_factory=dict)
    knowledge: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    # ── Validation ──────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """Return list of validation errors (empty = valid)."""
        errors: list[str] = []

        if not self.name or not self.name.strip():
            errors.append("'name' is required.")
        if not self.purpose or not self.purpose.strip():
            errors.append("'purpose' is required.")

        if not isinstance(self.skills, list):
            errors.append("'skills' must be a list.")
        if not isinstance(self.integrations, list):
            errors.append("'integrations' must be a list.")

        perm = self.permissions
        rl = perm.get("refund_limit", 0)
        if not isinstance(rl, (int, float)) or rl < 0:
            errors.append("'permissions.refund_limit' must be a non-negative number.")

        rt = self.runtime
        pl = rt.get("permission_level", 1)
        if not isinstance(pl, int) or not (0 <= pl <= 5):
            errors.append("'runtime.permission_level' must be 0–5.")

        return errors

    def is_valid(self) -> bool:
        return len(self.validate()) == 0

    # ── Business rule helpers ───────────────────────────────────────────────

    @property
    def refund_limit(self) -> float:
        return float(self.permissions.get("refund_limit", 0))

    @property
    def data_access(self) -> str:
        return str(self.permissions.get("data_access", "read_only"))

    @property
    def allowed_apis(self) -> list[str]:
        return list(self.permissions.get("allowed_apis", []))

    @property
    def rate_limits(self) -> dict[str, int]:
        return dict(self.permissions.get("rate_limits", {}))

    @property
    def restricted_commands(self) -> list[str]:
        return list(self.permissions.get("restricted_commands", []))

    @property
    def escalation_triggers(self) -> list[str]:
        return list(self.permissions.get("escalation_triggers", []))

    @property
    def permission_level(self) -> int:
        return int(self.runtime.get("permission_level", 1))

    @property
    def goal_tracking_enabled(self) -> bool:
        return bool(self.runtime.get("goal_tracking", True))

    @property
    def memory_enabled(self) -> bool:
        return bool(self.runtime.get("memory_enabled", True))

    # ── Serialisation ───────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "purpose": self.purpose,
            "skills": list(self.skills),
            "integrations": list(self.integrations),
            "permissions": dict(self.permissions),
            "knowledge": dict(self.knowledge),
            "runtime": dict(self.runtime),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_agent_kwargs(self) -> dict[str, Any]:
        """Convert manifest into kwargs compatible with BaseAgent.__init__."""
        return {
            "name": self.name,
            "role": self.purpose,
            "skills": list(self.skills),
            "tools": [],  # resolved dynamically from integrations
            "objectives": [self.purpose],
            "permissions": list(self.permissions.get("allowed_apis", [])),
            "permission_level": self.permission_level,
        }

    # ── Class methods ────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentManifest":
        """Build manifest from raw dict, filling missing keys with defaults."""
        defaults = json.loads(json.dumps(_MANIFEST_DEFAULTS))  # deep copy

        def _merge(base: dict, override: dict) -> dict:
            for k, v in override.items():
                if isinstance(v, dict) and isinstance(base.get(k), dict):
                    base[k] = _merge(base[k], v)
                else:
                    base[k] = v
            return base

        merged = _merge(defaults, data)
        return cls(
            name=str(merged.get("name", "")),
            purpose=str(merged.get("purpose", "")),
            version=str(merged.get("version", "1.0")),
            skills=list(merged.get("skills", [])),
            integrations=list(merged.get("integrations", [])),
            permissions=dict(merged.get("permissions", {})),
            knowledge=dict(merged.get("knowledge", {})),
            runtime=dict(merged.get("runtime", {})),
            metadata=dict(merged.get("metadata", {})),
            created_at=float(merged.get("created_at", time.time())),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "AgentManifest":
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_file(cls, path: str | Path) -> "AgentManifest":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Agent manifest not found: {path}")
        return cls.from_json(path.read_text(encoding="utf-8"))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    # ── Factory: build manifest from AgentSpec ───────────────────────────────

    @classmethod
    def from_spec(cls, spec: Any) -> "AgentManifest":
        """Convert an AgentSpec into an AgentManifest."""
        permissions_block: dict[str, Any] = {
            "refund_limit": spec.metadata.get("refund_limit", 0),
            "data_access": spec.metadata.get("data_access", "read_only"),
            "allowed_apis": list(spec.integrations),
            "rate_limits": dict(spec.metadata.get("rate_limits", {})),
            "restricted_commands": list(spec.metadata.get("restricted_commands", [])),
            "escalation_triggers": list(spec.metadata.get("escalation_triggers", [])),
        }
        knowledge_block: dict[str, Any] = {
            "documents": [s for s in spec.knowledge if not s.startswith("http")],
            "urls": [s for s in spec.knowledge if s.startswith("http")],
            "config": "knowledge/config.json",
        }
        runtime_block: dict[str, Any] = {
            "permission_level": spec.permission_level,
            "model": spec.metadata.get("model", ""),
            "provider": spec.metadata.get("provider", ""),
            "memory_enabled": True,
            "goal_tracking": True,
        }
        return cls(
            name=spec.name,
            purpose=spec.purpose,
            version=spec.version,
            skills=list(spec.skills),
            integrations=list(spec.integrations),
            permissions=permissions_block,
            knowledge=knowledge_block,
            runtime=runtime_block,
            metadata=dict(spec.metadata),
        )

    def __repr__(self) -> str:
        return (
            f"AgentManifest(name={self.name!r}, version={self.version!r}, "
            f"skills={self.skills}, integrations={self.integrations})"
        )
