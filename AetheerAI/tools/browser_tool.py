"""browser_tool — Open URLs and local files in the system's default browser."""
from __future__ import annotations
import webbrowser, logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def browser_tool(url: str, action: str = "open") -> str:
    """
    Interact with the system browser.

    url    : A full URL (https://...) or a local file path.
    action : open | new_tab | new_window

    Actions:
        open       : Open URL in the current/default browser session.
        new_tab    : Force a new browser tab.
        new_window : Force a new browser window.
    """
    if not url or not isinstance(url, str):
        return "Error: 'url' must be a non-empty string."

    url    = url.strip()
    action = (action or "open").strip().lower()

    # Validate URL scheme
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https", "file", ""}:
        return f"Error: Unsupported scheme '{parsed.scheme}'. Use http, https, or file."

    # If no scheme, assume https
    if not parsed.scheme:
        url = "https://" + url

    try:
        if action in ("open", ""):
            opened = webbrowser.open(url)
        elif action == "new_tab":
            opened = webbrowser.open_new_tab(url)
        elif action == "new_window":
            opened = webbrowser.open_new(url)
        else:
            return f"Unknown action '{action}'. Use: open, new_tab, new_window."
    except Exception as e:
        return f"Error opening browser: {e}"

    if opened:
        return f"Opened in browser: {url}"
    return f"Browser could not be launched for: {url}"
