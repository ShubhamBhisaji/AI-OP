"""
playwright_tool — Control a headless Chromium browser for dynamic web automation.

Requires:  pip install playwright
           playwright install chromium     (downloads ~170 MB browser binary once)

Use this for JavaScript-heavy SPAs (React/Angular/Vue) that fail with plain HTTP
requests, sites that require login, and multi-step browser workflows.

Actions
-------
  navigate     : Load a URL and return the page title + first 2 000 chars of text.
  get_text     : Return all visible text content from the current page.
  get_html     : Return the raw outer HTML of a CSS selector element.
  click        : Click an element matching a CSS selector.
  fill         : Type text into an input matching a CSS selector.
  select       : Choose an <option> by value in a <select> element.
  screenshot   : Take a PNG screenshot and save it to agent_output/screenshots/.
  evaluate     : Execute a JavaScript expression and return its result.
  scroll       : Scroll the page (down | up | to_bottom | to_top).
  wait_for     : Wait for a CSS selector to appear on the page (max 10 s).
  get_links    : Return all <a href> links on the current page.
  get_table    : Extract a table as CSV-like text by CSS selector.
  close        : Close the browser (cleanup).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Screenshot output directory
_SCREENSHOT_DIR = Path(__file__).parent.parent / "agent_output" / "screenshots"

# Module-level browser/page state (single persistent session per process)
_browser = None
_page    = None
_playwright_ctx = None


def playwright_tool(
    action: str,
    url: str = "",
    selector: str = "",
    value: str = "",
    expression: str = "",
    direction: str = "down",
    filename: str = "",
    headless: bool = True,
) -> str:
    """
    Drive a headless Chromium browser.

    action     : See module-level Actions list.
    url        : URL for 'navigate'.
    selector   : CSS selector for click/fill/wait_for/get_html/get_table/select.
    value      : Text to type (fill), option value (select), or JavaScript source (evaluate).
    expression : JavaScript expression for 'evaluate'.
    direction  : 'down'|'up'|'to_bottom'|'to_top' for 'scroll'.
    filename   : Filename (no path) for 'screenshot' (default: screenshot.png).
    headless   : Run browser without a visible window (default: True).
    """
    global _browser, _page, _playwright_ctx

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout  # type: ignore
    except ImportError:
        return (
            "Error: playwright is not installed.\n"
            "Install it with:\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        )

    action = (action or "").strip().lower()
    if not action:
        return "Error: 'action' is required."

    def _ensure_browser() -> str | None:
        global _browser, _page, _playwright_ctx
        if _browser is None:
            _playwright_ctx = sync_playwright().start()
            _browser = _playwright_ctx.chromium.launch(headless=headless)
            _page = _browser.new_page()
        return None

    try:
        if action == "navigate":
            if not url:
                return "Error: 'url' is required for navigate."
            err = _ensure_browser()
            if err:
                return err
            _page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            title = _page.title()
            body  = _page.inner_text("body")[:2_000]
            return f"Page: {title}\nURL: {_page.url}\n{'─'*60}\n{body}"

        if action == "get_text":
            if _page is None:
                return "Error: no page loaded. Use 'navigate' first."
            text = _page.inner_text("body")
            return text[:5_000] + ("\n[Truncated]" if len(text) > 5_000 else "")

        if action == "get_html":
            if _page is None:
                return "Error: no page loaded. Use 'navigate' first."
            sel = selector or "body"
            try:
                html = _page.inner_html(sel)
            except Exception as e:
                return f"Error getting HTML for '{sel}': {e}"
            return html[:5_000] + ("\n[Truncated]" if len(html) > 5_000 else "")

        if action == "click":
            if not selector:
                return "Error: 'selector' is required for click."
            if _page is None:
                return "Error: no page loaded. Use 'navigate' first."
            _page.click(selector, timeout=10_000)
            return f"Clicked: {selector}"

        if action == "fill":
            if not selector:
                return "Error: 'selector' is required for fill."
            if value == "":
                return "Error: 'value' (text to type) is required for fill."
            if _page is None:
                return "Error: no page loaded. Use 'navigate' first."
            _page.fill(selector, value)
            return f"Filled '{selector}' with text."

        if action == "select":
            if not selector:
                return "Error: 'selector' is required for select."
            if not value:
                return "Error: 'value' (option value) is required for select."
            if _page is None:
                return "Error: no page loaded. Use 'navigate' first."
            _page.select_option(selector, value=value)
            return f"Selected '{value}' in '{selector}'."

        if action == "screenshot":
            if _page is None:
                return "Error: no page loaded. Use 'navigate' first."
            _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            fname = (filename or "screenshot.png").replace("/", "_").replace("\\", "_")
            if not fname.lower().endswith(".png"):
                fname += ".png"
            out = _SCREENSHOT_DIR / fname
            _page.screenshot(path=str(out), full_page=True)
            return f"Screenshot saved: {out}"

        if action == "evaluate":
            js = expression or value
            if not js:
                return "Error: 'expression' is required for evaluate."
            if _page is None:
                return "Error: no page loaded. Use 'navigate' first."
            result = _page.evaluate(js)
            return str(result)

        if action == "scroll":
            if _page is None:
                return "Error: no page loaded. Use 'navigate' first."
            scripts = {
                "down":      "window.scrollBy(0, window.innerHeight)",
                "up":        "window.scrollBy(0, -window.innerHeight)",
                "to_bottom": "window.scrollTo(0, document.body.scrollHeight)",
                "to_top":    "window.scrollTo(0, 0)",
            }
            script = scripts.get(direction.lower())
            if not script:
                return f"Unknown direction '{direction}'. Use: down, up, to_bottom, to_top."
            _page.evaluate(script)
            return f"Scrolled {direction}."

        if action == "wait_for":
            if not selector:
                return "Error: 'selector' is required for wait_for."
            if _page is None:
                return "Error: no page loaded. Use 'navigate' first."
            try:
                _page.wait_for_selector(selector, timeout=10_000)
                return f"Element '{selector}' appeared on the page."
            except PWTimeout:
                return f"Timeout: '{selector}' did not appear within 10 seconds."

        if action == "get_links":
            if _page is None:
                return "Error: no page loaded. Use 'navigate' first."
            links = _page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => ({text: e.innerText.trim(), href: e.href}))"
            )
            if not links:
                return "No links found on the page."
            lines = [f"Links on {_page.url}:"]
            for lk in links[:50]:
                lines.append(f"  • {lk['text'][:60]}  →  {lk['href']}")
            return "\n".join(lines)

        if action == "get_table":
            sel = selector or "table"
            if _page is None:
                return "Error: no page loaded. Use 'navigate' first."
            try:
                rows = _page.eval_on_selector_all(
                    f"{sel} tr",
                    "rows => rows.map(r => Array.from(r.querySelectorAll('th,td')).map(c => c.innerText.trim()))"
                )
            except Exception as e:
                return f"Error extracting table '{sel}': {e}"
            if not rows:
                return f"No table rows found for '{sel}'."
            csv_lines = [",".join(f'"{cell}"' for cell in row) for row in rows[:100]]
            return "\n".join(csv_lines)

        if action == "close":
            if _browser is not None:
                _browser.close()
                if _playwright_ctx:
                    _playwright_ctx.stop()
            _browser = None
            _page    = None
            _playwright_ctx = None
            return "Browser closed."

        return f"Unknown action '{action}'. See module docstring for valid actions."

    except Exception as exc:
        logger.error("playwright_tool: %s", exc)
        return f"Error: {exc}"
