"""AetheerAI.security — Unified security, guardrails, and policy enforcement."""

from .action_gate import ActionGate
from .action_proxy import ActionCategory, ActionProxy, GatedHTTPTransport, ProxyResult
from .approval_gate import ApprovalGate
from .audit_logger import AuditLogger
from .enforcement_gate import EnforcementGate, PolicyViolation
from .guardrail_controller import GuardrailController, GuardrailRules, GuardrailVerdict
from .policy_engine import PermissionLevel, PolicyDecision, PolicyEngine

__all__ = [
    # Gate layer
    "ActionGate",
    "ActionProxy",
    "ActionCategory",
    "ProxyResult",
    "GatedHTTPTransport",
    # Approval
    "ApprovalGate",
    "EnforcementGate",
    "PolicyViolation",
    # Audit
    "AuditLogger",
    # Guardrails
    "GuardrailController",
    "GuardrailRules",
    "GuardrailVerdict",
    # Policy
    "PolicyEngine",
    "PolicyDecision",
    "PermissionLevel",
]
