"""Failure clustering utilities for self-improvement feedback."""

from __future__ import annotations

from typing import Any


def _cluster_key(item: dict[str, Any]) -> str:
    if item.get("error"):
        return f"error:{str(item['error']).split(':')[0].strip().lower()}"
    expected = str(item.get("expected_contains") or "").strip().lower()
    if expected:
        return f"missing:{expected[:60]}"
    return "unknown"


def cluster_failures(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    clusters: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        if item.get("passed"):
            continue
        key = _cluster_key(item)
        clusters.setdefault(key, []).append(item)
    return clusters
