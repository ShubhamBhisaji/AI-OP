"""http_client — Make HTTP GET/POST requests with a simple interface."""
from __future__ import annotations
import json, logging
import urllib.request
import urllib.parse
import urllib.error

logger = logging.getLogger(__name__)

_TIMEOUT = 15          # seconds
_MAX_BODY = 20_000     # chars to display from response body


def http_client(
    url: str,
    method: str = "GET",
    body: str = "",
    headers: str = "",
) -> str:
    """
    Perform an HTTP request.

    url     : Full URL including scheme (https://...).
    method  : GET | POST | PUT | DELETE | HEAD (default: GET).
    body    : Request body for POST/PUT (plain text or JSON string).
    headers : JSON object of extra headers, e.g. '{"Authorization":"Bearer TOKEN"}'.

    Returns: HTTP status line, response headers summary, and body.
    """
    if not url or not isinstance(url, str):
        return "Error: 'url' must be a non-empty string."

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return "Error: URL must start with http:// or https://"

    method = (method or "GET").strip().upper()
    if method not in {"GET", "POST", "PUT", "DELETE", "HEAD", "PATCH"}:
        return f"Error: Unsupported method '{method}'. Use GET, POST, PUT, DELETE, HEAD, or PATCH."

    # Parse extra headers
    extra_headers: dict[str, str] = {}
    if headers and headers.strip():
        try:
            parsed = json.loads(headers)
            if not isinstance(parsed, dict):
                return "Error: 'headers' must be a JSON object."
            extra_headers = {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError as e:
            return f"Error parsing headers JSON: {e}"

    # Block header injection via CRLF
    for k, v in extra_headers.items():
        if "\n" in k or "\r" in k or "\n" in v or "\r" in v:
            return "Error: Header names/values must not contain newline characters."

    # Prepare body
    body_bytes: bytes | None = None
    if body and body.strip():
        body_bytes = body.encode("utf-8")
        if "Content-Type" not in extra_headers:
            extra_headers["Content-Type"] = (
                "application/json" if body.strip().startswith("{") else "text/plain"
            )

    req = urllib.request.Request(url, data=body_bytes, method=method)
    for k, v in extra_headers.items():
        req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            status  = resp.status
            reason  = resp.reason
            hdrs    = dict(resp.headers)
            content = resp.read(_MAX_BODY).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        content = e.read(_MAX_BODY).decode("utf-8", errors="replace")
        return (
            f"HTTP {e.code} {e.reason}\n"
            f"{'─'*40}\n"
            f"{content[:_MAX_BODY]}"
        )
    except urllib.error.URLError as e:
        return f"Request failed: {e.reason}"
    except TimeoutError:
        return f"Request timed out after {_TIMEOUT}s."

    content_type = hdrs.get("Content-Type", "")
    # Pretty-print JSON responses
    if "json" in content_type.lower():
        try:
            content = json.dumps(json.loads(content), indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            pass

    truncated = f"\n\n[Body truncated at {_MAX_BODY} chars]" if len(content) >= _MAX_BODY else ""
    return (
        f"HTTP {status} {reason}\n"
        f"Content-Type: {content_type}\n"
        f"{'─'*40}\n"
        f"{content}{truncated}"
    )
