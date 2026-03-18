"""Output credential redaction — scans text for leaked secrets and redacts them."""

from __future__ import annotations

import re

_REDACTED = "[REDACTED]"

# Compiled patterns for common credential formats.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # AWS access key IDs
    ("aws_key", re.compile(r"(?<![A-Za-z0-9])(AKIA[0-9A-Z]{16})(?![A-Za-z0-9])")),
    # OpenAI / Anthropic / Stripe / generic sk- keys
    ("sk_key", re.compile(r"(?<![A-Za-z0-9_\-])(sk-[A-Za-z0-9_\-]{20,})(?![A-Za-z0-9_\-])")),
    # GitHub tokens (classic PAT, fine-grained, user-to-server)
    ("github_token", re.compile(r"(?<![A-Za-z0-9_])(gh[pousr]_[A-Za-z0-9_]{20,})(?![A-Za-z0-9_])")),
    # Slack tokens
    ("slack_token", re.compile(r"(?<![A-Za-z0-9_\-])(xox[bpas]-[A-Za-z0-9\-]{10,})(?![A-Za-z0-9_\-])")),
    # Connection strings with credentials (postgresql://, redis://, mongodb://, mysql://)
    ("conn_string", re.compile(
        r"((?:postgresql|postgres|redis|rediss|mongodb|mongodb\+srv|mysql|amqp|amqps)"
        r"://[^\s\"'`]+@[^\s\"'`]+)",
        re.IGNORECASE,
    )),
    # JWT tokens (three dot-separated base64 segments)
    ("jwt", re.compile(r"(?<![A-Za-z0-9_\-.])(eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})(?![A-Za-z0-9_\-.])"))  ,
    # Generic key=value patterns for password/secret/token (quoted or unquoted)
    ("kv_secret", re.compile(
        r"(?i)((?:password|passwd|secret|api_key|apikey|access_token|auth_token)"
        r'\s*[=:]\s*["\']?[^\s"\']{8,})',
    )),
]


def redact_credentials(text: str) -> str:
    """Return *text* with any detected credentials replaced by [REDACTED]."""
    if not text:
        return text
    result = text
    for _name, pattern in _PATTERNS:
        result = pattern.sub(_REDACTED, result)
    return result


def contains_credentials(text: str) -> list[str]:
    """Return names of credential patterns detected (empty list if clean)."""
    if not text:
        return []
    found: list[str] = []
    for name, pattern in _PATTERNS:
        if pattern.search(text):
            found.append(name)
    return found
