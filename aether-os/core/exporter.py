"""Exporter service facade for agent/system export operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.aether_kernel import AetherKernel


class ExporterService:
    """
    Thin export orchestration layer.

    This service intentionally delegates to kernel implementation methods for
    backward compatibility while we progressively migrate template/codegen
    responsibilities out of AetherKernel.
    """

    def __init__(self, kernel: "AetherKernel") -> None:
        self._kernel = kernel

    def export_agent(self, name: str) -> dict:
        return self._kernel._export_agent_impl(name)

    def export_system(self, system_name: str, agent_names: list[str]) -> dict:
        return self._kernel._export_system_impl(system_name, agent_names)
