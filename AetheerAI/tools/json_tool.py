"""json_tool — Parse, validate, format, query, and transform JSON."""
from __future__ import annotations
import json, logging

logger = logging.getLogger(__name__)

def json_tool(action: str, data: str, key: str = "") -> str:
    """
    Perform JSON operations.

    Actions:
        format   : Pretty-print JSON (2-space indent).
        validate : Check if `data` is valid JSON.
        get      : Extract value at dot-path `key` (e.g. "user.name").
        keys     : List top-level keys of a JSON object.
        minify   : Compact JSON (no whitespace).
        to_list  : Return JSON array items one per line.
    """
    action = (action or "").strip().lower()
    if not data:
        return "Error: data cannot be empty."

    if action == "format":
        try:
            return json.dumps(json.loads(data), indent=2, ensure_ascii=False)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

    if action == "validate":
        try:
            json.loads(data)
            return "Valid JSON."
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

    if action == "minify":
        try:
            return json.dumps(json.loads(data), separators=(",", ":"), ensure_ascii=False)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

    if action == "keys":
        try:
            parsed = json.loads(data)
            if not isinstance(parsed, dict):
                return "Error: JSON root is not an object."
            return "\n".join(parsed.keys())
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

    if action == "get":
        if not key:
            return "Error: 'key' required for 'get' action."
        try:
            parsed = json.loads(data)
            parts = key.split(".")
            cur = parsed
            for p in parts:
                if isinstance(cur, dict):
                    cur = cur[p]
                elif isinstance(cur, list):
                    cur = cur[int(p)]
                else:
                    return f"Error: cannot traverse into {type(cur).__name__}."
            return json.dumps(cur, indent=2, ensure_ascii=False) if isinstance(cur, (dict, list)) else str(cur)
        except (KeyError, IndexError) as e:
            return f"Key not found: {e}"
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

    if action == "to_list":
        try:
            parsed = json.loads(data)
            if not isinstance(parsed, list):
                return "Error: JSON root is not an array."
            return "\n".join(json.dumps(item, ensure_ascii=False) for item in parsed)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

    return f"Unknown action '{action}'. Use: format, validate, minify, keys, get, to_list."
