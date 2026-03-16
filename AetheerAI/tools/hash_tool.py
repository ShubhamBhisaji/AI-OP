"""hash_tool — Compute cryptographic hashes of text or files."""
from __future__ import annotations
import hashlib, logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SUPPORTED = {"md5", "sha1", "sha256", "sha512", "sha224", "sha384", "blake2b", "blake2s"}


def hash_tool(text: str, algorithm: str = "sha256") -> str:
    """
    Compute a hash of text or a file.

    text      : The string to hash, OR a file path prefixed with 'file:'.
                Examples:
                  "Hello World"           → hash the string
                  "file:C:/path/to/file"  → hash the file
    algorithm : md5 | sha1 | sha224 | sha256 | sha384 | sha512 | blake2b | blake2s
                Default: sha256.  Use 'all' to compute with every algorithm.
    """
    if not isinstance(text, str):
        return "Error: 'text' must be a string or 'file:<path>'."

    algo = (algorithm or "sha256").strip().lower()

    if algo == "all":
        algorithms = sorted(_SUPPORTED)
    elif algo not in _SUPPORTED:
        return f"Error: Unsupported algorithm '{algo}'. Choose from: {', '.join(sorted(_SUPPORTED))} or 'all'."
    else:
        algorithms = [algo]

    # Determine source bytes
    raw = text.strip()
    if raw.startswith("file:"):
        path = Path(raw[5:].strip())
        if not path.exists():
            return f"Error: File not found — {path}"
        if not path.is_file():
            return f"Error: Not a file — {path}"
        try:
            data = path.read_bytes()
        except PermissionError:
            return f"Error: Permission denied reading {path}"
        source_desc = f"File: {path.name}  ({len(data):,} bytes)"
    else:
        data = raw.encode("utf-8")
        preview = (raw[:60] + "...") if len(raw) > 60 else raw
        source_desc = f"String: \"{preview}\""

    lines = [source_desc, "─" * 50]
    for name in algorithms:
        try:
            h = hashlib.new(name, data)
            lines.append(f"{name.upper():<10}: {h.hexdigest()}")
        except Exception as e:
            lines.append(f"{name.upper():<10}: Error — {e}")

    return "\n".join(lines)
