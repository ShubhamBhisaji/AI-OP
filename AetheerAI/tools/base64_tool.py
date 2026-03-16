"""base64_tool — Encode and decode Base64 (standard, URL-safe, and URL decoding)."""
from __future__ import annotations
import base64, logging
from urllib.parse import quote, unquote

logger = logging.getLogger(__name__)


def base64_tool(action: str, data: str) -> str:
    """
    Encode or decode data using Base64 (or URL encoding).

    action : encode | decode | url_encode | url_decode | encode_url | decode_url
    data   : The string to process.

    Actions:
        encode     : Base64-encode the input string (standard alphabet).
        decode     : Base64-decode the input back to a string.
        encode_url : Base64-encode with URL-safe alphabet (- instead of +, _ instead of /).
        decode_url : Base64-decode with URL-safe alphabet.
        url_encode : Percent-encode a string for use in a URL (e.g. spaces → %20).
        url_decode : Decode a percent-encoded URL string.
    """
    if not action or not isinstance(action, str):
        return "Error: 'action' is required."

    action = action.strip().lower()

    if not isinstance(data, str):
        data = str(data)

    if action == "encode":
        try:
            result = base64.b64encode(data.encode("utf-8")).decode("ascii")
            return f"Base64: {result}"
        except Exception as e:
            return f"Error encoding: {e}"

    if action == "decode":
        try:
            # Add padding if missing
            padded = data.strip() + "=" * (-len(data.strip()) % 4)
            result = base64.b64decode(padded).decode("utf-8", errors="replace")
            return f"Decoded: {result}"
        except Exception as e:
            return f"Error decoding: {e}"

    if action == "encode_url":
        try:
            result = base64.urlsafe_b64encode(data.encode("utf-8")).decode("ascii")
            return f"URL-safe Base64: {result}"
        except Exception as e:
            return f"Error encoding (URL-safe): {e}"

    if action == "decode_url":
        try:
            padded = data.strip() + "=" * (-len(data.strip()) % 4)
            result = base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
            return f"Decoded (URL-safe): {result}"
        except Exception as e:
            return f"Error decoding (URL-safe): {e}"

    if action == "url_encode":
        return f"URL-encoded: {quote(data, safe='')}"

    if action == "url_decode":
        return f"URL-decoded: {unquote(data)}"

    return f"Unknown action '{action}'. Use: encode, decode, encode_url, decode_url, url_encode, url_decode."
