"""Compiler service facade for generated app build operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.aether_kernel import AetherKernel


class CompilerService:
    """Thin compiler facade delegating to kernel build implementation."""

    def __init__(self, kernel: "AetherKernel") -> None:
        self._kernel = kernel

    def build_application(self, app_name: str, progress=None) -> dict[str, Any]:
        return self._kernel._build_application_impl(app_name, progress=progress)
