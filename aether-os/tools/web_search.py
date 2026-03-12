"""
web_search — Tool that performs a web search and returns summarized results.
Uses the DuckDuckGo Instant Answer API (no API key required).
Falls back to a mock response when the network is unavailable.
"""

from __future__ import annotations

import logging
import urllib.parse
import urllib.request
import json

logger = logging.getLogger(__name__)

_DDG_URL = "https://api.duckduckgo.com/?q={query}&format=json&no_html=1&skip_disambig=1"


def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web for `query` and return a plain-text summary.

    Args:
        query       : The search query string.
        max_results : Maximum number of related topics to include.

    Returns:
        A newline-separated string of search result summaries.
    """
    if not query or not isinstance(query, str):
        return "Error: query must be a non-empty string."

    encoded = urllib.parse.quote_plus(query)
    url = _DDG_URL.format(query=encoded)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AetheerAI/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("web_search: network error — %s", exc)
        return f"[Mock Result] Search results for '{query}': No live results (offline mode)."

    lines: list[str] = []

    # Abstract (top answer)
    abstract = data.get("AbstractText", "").strip()
    if abstract:
        source = data.get("AbstractSource", "")
        lines.append(f"Summary ({source}): {abstract}")

    # Answer (e.g. calculator / conversion)
    answer = data.get("Answer", "").strip()
    if answer:
        lines.append(f"Answer: {answer}")

    # Related topics
    for topic in data.get("RelatedTopics", [])[:max_results]:
        text = topic.get("Text", "").strip()
        href = topic.get("FirstURL", "")
        if text:
            lines.append(f"- {text}" + (f" [{href}]" if href else ""))

    if not lines:
        lines.append(f"No results found for '{query}'.")

    return "\n".join(lines)
