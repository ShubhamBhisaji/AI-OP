"""
vision_tool — Analyze images using AI vision APIs.

Supported providers (auto-detected from env vars):
  • OpenAI GPT-4o / GPT-4-vision  — OPENAI_API_KEY
  • Anthropic Claude 3 / 3.5      — ANTHROPIC_API_KEY
  • Google Gemini 1.5 Pro          — GEMINI_API_KEY

Env vars (first non-empty key wins):
    OPENAI_API_KEY
    ANTHROPIC_API_KEY
    GEMINI_API_KEY

Actions
-------
  describe  : Describe what is in the image in natural language.
  extract   : Extract all visible text (OCR-like).
  analyze   : Answer a specific question about the image.
  code_ui   : Look at a UI screenshot and generate HTML/CSS/Tailwind code to recreate it.
  audit     : Security / accessibility audit of a screenshot.

Input formats (mutually exclusive):
  image_path : Absolute or relative path to a PNG/JPG/WEBP file on disk.
  image_url  : Public HTTPS URL of an image.
  image_b64  : Raw base64-encoded image data (with or without data URI prefix).
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Project root used for sandboxing local image paths
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()

_PROMPTS = {
    "describe": "Describe this image in detail. Include objects, people, colors, layout, and context.",
    "extract":  "Extract ALL visible text from this image exactly as it appears. Format it clearly.",
    "code_ui":  (
        "You are a senior frontend developer. Look at this UI screenshot and write complete, "
        "production-ready HTML with Tailwind CSS classes to recreate this exact design. "
        "Output only the HTML code."
    ),
    "audit": (
        "Perform a combined security and accessibility audit of this screenshot. "
        "List: (1) visible security concerns, (2) WCAG accessibility issues, "
        "(3) UX problems. Be specific and actionable."
    ),
}


def vision_tool(
    action: str = "describe",
    image_path: str = "",
    image_url: str = "",
    image_b64: str = "",
    question: str = "",
    provider: str = "",
) -> str:
    """
    Analyze an image with an AI vision model.

    action      : describe | extract | analyze | code_ui | audit
    image_path  : Local file path (sandboxed to project directory).
    image_url   : Public HTTPS URL of the image.
    image_b64   : Base64-encoded image data.
    question    : Custom question for 'analyze' action.
    provider    : Force a specific provider: openai | anthropic | gemini.
                  If omitted, the first available API key is used.
    """
    action = (action or "describe").strip().lower()

    # Build prompt
    if action == "analyze":
        if not question:
            return "Error: 'question' is required for 'analyze' action."
        prompt = question
    else:
        prompt = _PROMPTS.get(action)
        if prompt is None:
            return f"Unknown action '{action}'. Use: describe, extract, analyze, code_ui, audit."

    # Resolve image
    b64_data, mime = _resolve_image(image_path, image_url, image_b64)
    if b64_data is None:
        return mime  # error message

    # Select provider
    prov = (provider or "").strip().lower()
    openai_key    = os.environ.get("OPENAI_API_KEY", "").strip()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    gemini_key    = os.environ.get("GEMINI_API_KEY", "").strip()

    if prov == "openai" or (not prov and openai_key):
        return _call_openai(b64_data, mime, prompt, openai_key)
    if prov == "anthropic" or (not prov and anthropic_key):
        return _call_anthropic(b64_data, mime, prompt, anthropic_key)
    if prov == "gemini" or (not prov and gemini_key):
        return _call_gemini(b64_data, mime, prompt, gemini_key)

    return (
        "Error: No vision-capable API key found.\n"
        "Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY in your .env file."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Image resolution helpers
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_image(
    image_path: str,
    image_url: str,
    image_b64: str,
) -> tuple[str | None, str]:
    """Return (base64_data, mime_type) or (None, error_message)."""
    if image_b64:
        # Strip data URI prefix if present
        if "," in image_b64:
            header, image_b64 = image_b64.split(",", 1)
            mime = header.split(":")[1].split(";")[0] if ":" in header else "image/jpeg"
        else:
            mime = "image/jpeg"
        return image_b64.strip(), mime

    if image_path:
        p = Path(image_path)
        if not p.is_absolute():
            p = (_PROJECT_ROOT / p).resolve()
        else:
            p = p.resolve()
        # Sandbox check
        pr = str(_PROJECT_ROOT)
        if not (str(p) == pr or str(p).startswith(pr + os.sep)):
            return None, "❌ Security: image path is outside the project directory."
        if not p.exists():
            return None, f"Error: File not found — {p}"
        suffix = p.suffix.lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
        mime = mime_map.get(suffix, "image/jpeg")
        data = base64.b64encode(p.read_bytes()).decode("utf-8")
        return data, mime

    if image_url:
        # Download and base64-encode
        import urllib.request, urllib.error
        if not image_url.startswith("https://"):
            return None, "Error: image_url must start with https://"
        try:
            req = urllib.request.Request(image_url, headers={"User-Agent": "AetheerAI/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read(10 * 1024 * 1024)  # 10 MB limit
                ct  = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        except Exception as e:
            return None, f"Error downloading image: {e}"
        return base64.b64encode(raw).decode("utf-8"), ct

    return None, "Error: provide image_path, image_url, or image_b64."


# ──────────────────────────────────────────────────────────────────────────────
# Provider backends
# ──────────────────────────────────────────────────────────────────────────────

def _call_openai(b64: str, mime: str, prompt: str, api_key: str) -> str:
    if not api_key:
        return "Error: OPENAI_API_KEY is not set."
    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            max_tokens=2048,
        )
        return response.choices[0].message.content or ""
    except ImportError:
        return "Error: openai package not installed. Run: pip install openai"
    except Exception as exc:
        return f"OpenAI Vision error: {exc}"


def _call_anthropic(b64: str, mime: str, prompt: str, api_key: str) -> str:
    if not api_key:
        return "Error: ANTHROPIC_API_KEY is not set."
    try:
        from anthropic import Anthropic  # type: ignore
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": mime, "data": b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return response.content[0].text if response.content else ""
    except ImportError:
        return "Error: anthropic package not installed. Run: pip install anthropic"
    except Exception as exc:
        return f"Anthropic Vision error: {exc}"


def _call_gemini(b64: str, mime: str, prompt: str, api_key: str) -> str:
    if not api_key:
        return "Error: GEMINI_API_KEY is not set."
    import json as _json, urllib.request, urllib.error
    payload = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": mime, "data": b64}},
                {"text": prompt},
            ]
        }]
    }
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-1.5-pro:generateContent?key={api_key}"
    )
    body = _json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(endpoint, data=body,
                                   headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except urllib.error.HTTPError as exc:
        try:
            detail = _json.loads(exc.read().decode("utf-8"))
            msg = detail.get("error", {}).get("message", str(exc))
        except Exception:
            msg = str(exc)
        return f"Gemini Vision error ({exc.code}): {msg}"
    except Exception as exc:
        return f"Gemini Vision error: {exc}"
