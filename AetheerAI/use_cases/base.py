"""
use_cases/base.py — Abstract base class and registry for Use Case Packs.

A UseCase Pack is the "fuel" layer above the AetheerAI engine:
  - Encapsulates a specific, opinionated multi-agent workflow
  - Accepts simple named inputs (no agent-configuration knowledge required)
  - Produces a concrete, file-backed deliverable
  - Is discoverable via `registry.list()` and runnable via `registry.run(name, inputs, kernel)`
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InputField:
    """Describes one required or optional input for a use case."""
    name: str
    description: str
    required: bool = True
    default: Any = None
    example: str = ""


@dataclass
class UseCaseResult:
    """Standardised result envelope returned by every use case."""
    success: bool
    summary: str
    outputs: dict[str, Any] = field(default_factory=dict)
    # output_files: list of (label, absolute_path) tuples
    output_files: list[tuple[str, str]] = field(default_factory=list)
    error: str | None = None


class UseCase(ABC):
    """
    Abstract base class for all use-case packs.

    Subclasses implement:
      name        — machine-readable slug  (e.g. "content_factory")
      title       — human-readable name    (e.g. "Content Factory")
      description — one-sentence summary
      inputs      — list[InputField]  describing accepted parameters
      run()       — executes the workflow and returns a UseCaseResult
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def title(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def inputs(self) -> list[InputField]: ...

    @abstractmethod
    def run(self, inputs: dict[str, Any], kernel) -> UseCaseResult: ...

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def validate_inputs(self, inputs: dict[str, Any]) -> None:
        """Raise ValueError if a required field is missing or blank."""
        if not isinstance(inputs, dict):
            raise TypeError(f"UseCase '{self.name}': inputs must be a dict, got {type(inputs).__name__}.")
        for field_def in self.inputs:
            if field_def.required:
                val = inputs.get(field_def.name)
                if val is None or (isinstance(val, str) and not val.strip()):
                    raise ValueError(
                        f"UseCase '{self.name}': required input '{field_def.name}' is missing or empty."
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputs": [
                {
                    "name": f.name,
                    "description": f.description,
                    "required": f.required,
                    "default": f.default,
                    "example": f.example,
                }
                for f in self.inputs
            ],
        }

    def __repr__(self) -> str:
        return f"<UseCase name={self.name!r}>"


class UseCaseRegistry:
    """Central registry for all installed use-case packs."""

    def __init__(self) -> None:
        self._packs: dict[str, UseCase] = {}

    def register(self, pack: UseCase) -> None:
        if not isinstance(pack, UseCase):
            raise TypeError(f"UseCaseRegistry.register: expected UseCase, got {type(pack).__name__}.")
        self._packs[pack.name] = pack
        logger.debug("UseCaseRegistry: registered pack '%s'.", pack.name)

    def get(self, name: str) -> UseCase | None:
        if not isinstance(name, str) or not name.strip():
            return None
        return self._packs.get(name.strip().lower())

    def list(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self._packs.values()]

    def run(self, name: str, inputs: dict[str, Any], kernel) -> UseCaseResult:
        """
        Look up a pack by name, validate inputs, and execute it.

        Parameters
        ----------
        name   : Use-case slug (e.g. "content_factory")
        inputs : Dict of named inputs matching the pack's InputField definitions
        kernel : AetheerAiKernel instance

        Returns UseCaseResult — always, never raises.
        """
        pack = self.get(name)
        if pack is None:
            available = ", ".join(self._packs.keys()) or "none registered"
            return UseCaseResult(
                success=False,
                summary="",
                error=f"No use case named '{name}'. Available: {available}",
            )
        try:
            pack.validate_inputs(inputs)
        except (ValueError, TypeError) as exc:
            return UseCaseResult(success=False, summary="", error=str(exc))
        try:
            return pack.run(inputs, kernel)
        except Exception as exc:  # noqa: BLE001
            logger.error("UseCaseRegistry: pack '%s' raised: %s", name, exc, exc_info=True)
            return UseCaseResult(success=False, summary="", error=str(exc))
