"""Governance and safety controls for autonomous workflows."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from security.approval_gate import ApprovalGate

logger = logging.getLogger(__name__)


ManualOverrideCallback = Callable[[str, dict[str, Any]], str | None]


@dataclass
class GovernanceContext:
    workflow_id: str
    max_runtime_seconds: int
    max_budget_usd: float
    started_at: float = field(default_factory=time.time)
    spent_usd: float = 0.0
    cancelled: bool = False
    cancel_reason: str = ""

    def elapsed_seconds(self) -> float:
        return time.time() - self.started_at


class GovernanceLayer:
    """Centralized policy checks for runtime safety and operator control."""

    def __init__(self, manual_override: ManualOverrideCallback | None = None):
        self.manual_override = manual_override

    def check_limits(self, ctx: GovernanceContext) -> None:
        if ctx.cancelled:
            raise RuntimeError(ctx.cancel_reason or "Workflow cancelled by manual override.")

        if ctx.max_runtime_seconds > 0 and ctx.elapsed_seconds() > ctx.max_runtime_seconds:
            raise TimeoutError(
                f"Workflow exceeded runtime limit ({ctx.max_runtime_seconds}s)."
            )

        if ctx.max_budget_usd > 0 and ctx.spent_usd > ctx.max_budget_usd:
            raise RuntimeError(
                f"Workflow exceeded budget limit (${ctx.max_budget_usd:.2f})."
            )

    def add_spend(self, ctx: GovernanceContext, usd: float) -> None:
        if usd <= 0:
            return
        ctx.spent_usd += usd

    def require_risky_approval(
        self,
        *,
        agent_name: str,
        summary: str,
        tool_name: str = "autonomous_task_execution",
    ) -> None:
        """Request explicit operator approval for risky workflow actions."""
        ApprovalGate.request(
            tool_name=tool_name,
            agent_name=agent_name,
            args_summary=summary,
            force=True,
        )

    def run_manual_override(self, event: str, payload: dict[str, Any], ctx: GovernanceContext) -> None:
        """Invoke manual override callback and apply actions if requested."""
        if self.manual_override is None:
            return

        action = self.manual_override(event, payload)
        if not action:
            return

        normalized = action.strip().lower()
        if normalized in {"cancel", "stop", "abort"}:
            ctx.cancelled = True
            ctx.cancel_reason = f"Manual override requested cancellation at event '{event}'."
            logger.warning("GovernanceLayer: workflow '%s' cancelled by manual override.", ctx.workflow_id)
            return

        if normalized in {"approve", "continue"}:
            logger.info("GovernanceLayer: manual override approved event '%s'.", event)
            return

        logger.info("GovernanceLayer: manual override returned '%s' for event '%s'.", normalized, event)

    @staticmethod
    def is_risky_task(require_approval: bool, text: str) -> bool:
        """Heuristic used for pre-execution approval prompts."""
        if require_approval:
            return True

        lower = text.lower()
        risky_markers = (
            "write",
            "delete",
            "terminal",
            "execute",
            "deploy",
            "send",
            "email",
            "slack",
            "discord",
            "github",
            "database",
            "sql",
            "kubernetes",
            "aws",
            "gcp",
        )
        return any(marker in lower for marker in risky_markers)
