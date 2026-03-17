"""Environment variable helpers for integration configuration."""
from __future__ import annotations

import os

from integrations.errors import ConfigurationError


_TRUE_VALUES = {"1", "true", "yes", "on"}


def env_required(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise ConfigurationError(
            f"Missing required environment variable: {name}"
        )
    return value


def env_optional(name: str, default: str = "") -> str:
    value = (os.environ.get(name) or "").strip()
    return value if value else default


def env_int(name: str, default: int) -> int:
    value = (os.environ.get(name) or "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(
            f"Environment variable {name} must be an integer"
        ) from exc


def env_bool(name: str, default: bool = False) -> bool:
    value = (os.environ.get(name) or "").strip().lower()
    if not value:
        return default
    return value in _TRUE_VALUES


def mask_secret(value: str, *, keep: int = 4) -> str:
    """Mask secrets for safe logs and diagnostics."""
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return ("*" * (len(value) - keep)) + value[-keep:]
