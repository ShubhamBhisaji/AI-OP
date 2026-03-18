"""Prompt injection pre-flight scanner — lightweight regex-based detection.

Scans user messages for common prompt injection patterns before they reach the
LLM.  Does NOT block by default — returns a ScanResult so callers can decide
(log, warn, or reject).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("aetheer.security.prompt_scanner")

# Each pattern: (flag_name, compiled regex, case-insensitive by default)
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # System prompt override attempts
    ("system_override", re.compile(
        r"(?:ignore|disregard|forget|override|bypass)\s+"
        r"(?:all\s+)?(?:previous|prior|above|earlier|existing|your)\s+"
        r"(?:instructions|prompts?|rules?|guidelines?|directives?|context)",
        re.IGNORECASE,
    )),
    ("new_identity", re.compile(
        r"(?:you\s+are\s+now|act\s+as\s+if|pretend\s+(?:you(?:'re| are)|to\s+be)|"
        r"from\s+now\s+on\s+you\s+are|new\s+instructions?:)",
        re.IGNORECASE,
    )),
    # Role/delimiter confusion
    ("role_injection", re.compile(
        r"<\|im_start\|>|<\|im_end\|>|\[system\]|\[INST\]|<<SYS>>|<\|system\|>",
        re.IGNORECASE,
    )),
    # Data exfiltration commands embedded in prompts
    ("exfil_command", re.compile(
        r"(?:^|\s)(?:curl|wget|nc|ncat|netcat)\s+(?:https?://|ftp://|\d{1,3}\.\d{1,3})",
        re.IGNORECASE,
    )),
    # Prompt leaking attempts
    ("prompt_leak", re.compile(
        r"(?:repeat|show|print|output|display|reveal|dump)\s+"
        r"(?:your\s+)?(?:system\s+)?(?:prompt|instructions|rules|initial\s+message)",
        re.IGNORECASE,
    )),
    # Encoded payload markers (base64 instructions)
    ("encoded_payload", re.compile(
        r"(?:decode|base64|atob|eval)\s*\(\s*['\"](?:[A-Za-z0-9+/]{20,}={0,2})['\"]",
        re.IGNORECASE,
    )),
]


@dataclass
class ScanResult:
    safe: bool = True
    flags: list[str] = field(default_factory=list)


def scan_messages(messages: list[dict[str, str]]) -> ScanResult:
    """Scan a list of chat messages for injection patterns.

    Only user/assistant messages are scanned — system messages are trusted.
    """
    result = ScanResult()
    for msg in messages:
        role = str(msg.get("role", "")).strip().lower()
        if role in ("system",):
            continue
        content = str(msg.get("content", ""))
        if not content:
            continue
        for flag_name, pattern in _INJECTION_PATTERNS:
            if pattern.search(content):
                if flag_name not in result.flags:
                    result.flags.append(flag_name)
                    result.safe = False
    if not result.safe:
        logger.warning("Prompt injection flags detected: %s", result.flags)
    return result


def scan_prompt(text: str) -> ScanResult:
    """Convenience wrapper to scan a single text string."""
    return scan_messages([{"role": "user", "content": text}])
