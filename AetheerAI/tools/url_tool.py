"""url_tool — Parse, build, encode, and inspect URLs."""
from __future__ import annotations
import json, logging
from urllib.parse import (
    urlparse, urlunparse, urlencode, parse_qs, quote, unquote, urljoin
)

logger = logging.getLogger(__name__)


def url_tool(action: str, url: str, params_json: str = "") -> str:
    """
    Work with URLs.

    action      : parse | build | encode | decode | join | extract_params | add_params
    url         : The URL to operate on (or the base URL for 'build'/'join').
    params_json : JSON object of parameters (for 'build', 'add_params').

    Actions:
        parse        : Break a URL into its components.
        build        : Construct a URL from a base + query params (JSON).
        encode       : Percent-encode the URL string.
        decode       : Percent-decode the URL string.
        join         : Resolve a relative URL against a base.
                       params_json = the relative path/URL to join.
        extract_params : Parse query string into a JSON object.
        add_params   : Append extra query params (JSON) to an existing URL.
    """
    if not action or not isinstance(action, str):
        return "Error: 'action' is required."

    action = action.strip().lower()
    url    = (url or "").strip()

    if action == "parse":
        if not url:
            return "Error: 'url' is required."
        p = urlparse(url)
        qs = parse_qs(p.query)
        qs_clean = {k: v[0] if len(v) == 1 else v for k, v in qs.items()}
        return (
            f"URL      : {url}\n"
            f"Scheme   : {p.scheme}\n"
            f"Host     : {p.hostname}\n"
            f"Port     : {p.port or '(default)'}\n"
            f"Path     : {p.path or '/'}\n"
            f"Params   : {json.dumps(qs_clean, ensure_ascii=False)}\n"
            f"Fragment : {p.fragment or '(none)'}\n"
            f"Username : {p.username or '(none)'}"
        )

    if action == "build":
        if not url:
            return "Error: 'url' (base URL) is required."
        params: dict = {}
        if params_json.strip():
            try:
                params = json.loads(params_json)
                if not isinstance(params, dict):
                    return "Error: 'params_json' must be a JSON object."
            except json.JSONDecodeError as e:
                return f"Error parsing params_json: {e}"
        qs = urlencode({str(k): str(v) for k, v in params.items()})
        p  = urlparse(url)
        built = urlunparse((p.scheme, p.netloc, p.path, p.params, qs, p.fragment))
        return f"Built URL: {built}"

    if action == "encode":
        if not url:
            return "Error: 'url' is required."
        safe_chars = ":/?#[]@!$&'()*+,;="
        return f"Encoded: {quote(url, safe=safe_chars)}"

    if action == "decode":
        if not url:
            return "Error: 'url' is required."
        return f"Decoded: {unquote(url)}"

    if action == "join":
        if not url:
            return "Error: 'url' (base URL) is required."
        relative = params_json.strip()
        if not relative:
            return "Error: Pass the relative URL/path in 'params_json'."
        return f"Joined: {urljoin(url, relative)}"

    if action == "extract_params":
        if not url:
            return "Error: 'url' is required."
        p  = urlparse(url)
        qs = parse_qs(p.query)
        clean = {k: v[0] if len(v) == 1 else v for k, v in qs.items()}
        if not clean:
            return "No query parameters found."
        return json.dumps(clean, indent=2, ensure_ascii=False)

    if action == "add_params":
        if not url:
            return "Error: 'url' is required."
        if not params_json.strip():
            return "Error: 'params_json' is required."
        try:
            extra = json.loads(params_json)
            if not isinstance(extra, dict):
                return "Error: 'params_json' must be a JSON object."
        except json.JSONDecodeError as e:
            return f"Error parsing params_json: {e}"
        p  = urlparse(url)
        existing = parse_qs(p.query)
        # Merge — extra params override existing
        for k, v in extra.items():
            existing[str(k)] = [str(v)]
        new_qs = urlencode({k: v[0] for k, v in existing.items()})
        updated = urlunparse((p.scheme, p.netloc, p.path, p.params, new_qs, p.fragment))
        return f"Updated URL: {updated}"

    return f"Unknown action '{action}'. Use: parse, build, encode, decode, join, extract_params, add_params."
