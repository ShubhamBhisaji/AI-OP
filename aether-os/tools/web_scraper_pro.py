"""
web_scraper_pro — Fetch a URL and extract clean article content as Markdown.

Requires:  pip install requests beautifulsoup4
Optional:  pip install markdownify   (produces cleaner Markdown output)

Unlike plain http_client, this tool:
  • Follows redirects and handles gzip-compressed responses.
  • Strips navigation bars, ads, scripts, styles, and footers.
  • Extracts just the main content block (article / main / body fallback).
  • Returns clean Markdown text ready to feed to an AI without burning tokens
    on HTML noise.

Actions
-------
  scrape    : Full scrape → return clean Markdown article content.
  summary   : Scrape + return only the first 500 words (fast overview).
  links     : Return all hyperlinks on the page.
  headings  : Return all heading text (h1–h4).
  images    : Return all image URLs and alt text.
  metadata  : Return page title, description, og:* and canonical URL.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any

logger = logging.getLogger(__name__)

_TIMEOUT   = 15     # seconds
_MAX_CHARS = 15_000 # output cap to keep context manageable

_REMOVE_TAGS = {
    "script", "style", "noscript", "nav", "header", "footer",
    "aside", "form", "iframe", "svg", "button", "input",
    "advertisement", "cookie-banner",
}

_UA = "Mozilla/5.0 (compatible; AetheerAI/1.0)"


def web_scraper_pro(url: str, action: str = "scrape") -> str:
    """
    Scrape a web page and return clean article content.

    url    : The full URL to fetch (must start with https:// or http://).
    action : scrape | summary | links | headings | images | metadata
    """
    if not url or not isinstance(url, str):
        return "Error: 'url' must be a non-empty string."

    url    = url.strip()
    action = (action or "scrape").strip().lower()

    # SSRF protection — block private / loopback ranges
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "Error: URL must start with http:// or https://"
    host = parsed.hostname or ""
    if _is_private_host(host):
        return "❌ Security: Requests to private/loopback addresses are not allowed."

    try:
        import requests                   # type: ignore
        from bs4 import BeautifulSoup     # type: ignore
    except ImportError as e:
        missing = "requests" if "requests" in str(e) else "beautifulsoup4"
        return (
            f"Error: '{missing}' is not installed.\n"
            f"Install with: pip install requests beautifulsoup4"
        )

    try:
        resp = requests.get(
            url,
            timeout=_TIMEOUT,
            headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"},
            allow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        return f"Error fetching URL: {exc}"

    soup = BeautifulSoup(html, "html.parser")

    # ── metadata ──────────────────────────────────────────────────────────
    if action == "metadata":
        title       = soup.title.get_text(strip=True) if soup.title else ""
        description = (
            (soup.find("meta", attrs={"name": "description"}) or {}).get("content", "")  # type: ignore[union-attr]
        )
        og: dict[str, str] = {}
        for tag in soup.find_all("meta", property=re.compile(r"^og:")):
            og[tag.get("property", "")] = tag.get("content", "")
        canonical_tag = soup.find("link", rel="canonical")
        canonical = canonical_tag.get("href", "") if canonical_tag else ""  # type: ignore[union-attr]
        lines = [
            f"Title       : {title}",
            f"Description : {description}",
            f"Canonical   : {canonical}",
        ]
        for k, v in og.items():
            lines.append(f"{k:<20}: {v}")
        return "\n".join(lines)

    # ── links ─────────────────────────────────────────────────────────────
    if action == "links":
        base = f"{parsed.scheme}://{parsed.netloc}"
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith("#") or href.startswith("javascript"):
                continue
            href = urllib.parse.urljoin(base, href)
            text = a.get_text(strip=True)[:80]
            links.append(f"  • {text}  →  {href}")
        if not links:
            return "No links found."
        return f"Links on {url}:\n" + "\n".join(links[:100])

    # ── images ────────────────────────────────────────────────────────────
    if action == "images":
        base  = f"{parsed.scheme}://{parsed.netloc}"
        lines = [f"Images on {url}:"]
        for img in soup.find_all("img"):
            src = img.get("src", "").strip()
            if not src:
                continue
            alt  = img.get("alt", "").strip()
            full = urllib.parse.urljoin(base, src)
            lines.append(f"  • [{alt or '(no alt)'}]  {full}")
        return "\n".join(lines[:100]) if len(lines) > 1 else "No images found."

    # ── headings ──────────────────────────────────────────────────────────
    if action == "headings":
        lines = [f"Headings on {url}:"]
        for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
            indent = "  " * (int(tag.name[1]) - 1)
            lines.append(f"{indent}{tag.name.upper()}: {tag.get_text(strip=True)}")
        return "\n".join(lines) if len(lines) > 1 else "No headings found."

    # ── scrape / summary ──────────────────────────────────────────────────
    # Remove noise tags
    for tag in soup(_REMOVE_TAGS):
        tag.decompose()

    # Try to find the main content container
    main = (
        soup.find("article")
        or soup.find("main")
        or soup.find("div", role="main")
        or soup.find(id=re.compile(r"content|article|main", re.I))
        or soup.find(class_=re.compile(r"content|article|post|blog", re.I))
        or soup.body
    )

    if main is None:
        return "Error: could not find page body."

    # Try markdownify for clean output; fall back to plain text
    try:
        import markdownify  # type: ignore
        md = markdownify.markdownify(str(main), heading_style="ATX", strip=["img"])
        # Collapse excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", md).strip()
    except ImportError:
        text = main.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if action == "summary":
        words = text.split()[:500]
        text  = " ".join(words) + (" …[summary truncated]" if len(text.split()) > 500 else "")

    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + f"\n\n[Truncated — {len(text):,} total chars]"

    return f"# {soup.title.get_text(strip=True) if soup.title else url}\nSource: {url}\n\n{text}"


# ──────────────────────────────────────────────────────────────────────────────
# SSRF protection helper
# ──────────────────────────────────────────────────────────────────────────────

def _is_private_host(host: str) -> bool:
    """Return True for loopback, link-local, and RFC-1918 addresses."""
    import ipaddress
    private_prefixes = ("localhost", "127.", "::1", "0.0.0.0")
    if any(host.startswith(p) for p in private_prefixes):
        return True
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        return False
