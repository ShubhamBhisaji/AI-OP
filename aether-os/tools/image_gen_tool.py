"""
image_gen_tool — Generate images with AI text-to-image APIs.

Supported backends (auto-detected from env vars):
  • DALL-E 3 (OpenAI)            — OPENAI_API_KEY
  • Stable Diffusion (REST API)  — STABILITY_API_KEY   (api.stability.ai)

Images are saved to agent_output/images/ and the path is returned.

Actions
-------
  generate  : Generate a new image from a text prompt.
  edit      : Edit/inpaint an existing image with a prompt (DALL-E only).
  variation : Create a variation of an existing image (DALL-E only).

Env vars:
    OPENAI_API_KEY      — Required for DALL-E 3.
    STABILITY_API_KEY   — Required for Stable Diffusion.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path(__file__).parent.parent / "agent_output" / "images"
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def image_gen_tool(
    action: str = "generate",
    prompt: str = "",
    image_path: str = "",
    mask_path: str = "",
    size: str = "1024x1024",
    quality: str = "standard",
    style: str = "vivid",
    n: int = 1,
    provider: str = "",
    filename: str = "",
) -> str:
    """
    Generate or edit images using an AI image model.

    action     : generate | edit | variation
    prompt     : Text prompt describing the image to generate.
    image_path : Source image for 'edit' or 'variation' (local path, sandboxed).
    mask_path  : Mask image for 'edit' — transparent areas will be regenerated.
    size       : Image dimensions: 1024x1024 | 1792x1024 | 1024x1792 (DALL-E 3).
    quality    : 'standard' or 'hd' (DALL-E 3 only).
    style      : 'vivid' or 'natural' (DALL-E 3 only).
    n          : Number of images to generate (1–4; DALL-E 2+ only).
    provider   : Force 'openai' or 'stability'. Auto-detected if omitted.
    filename   : Custom output filename (no extension, no path).
    """
    action = (action or "generate").strip().lower()
    if not prompt and action != "variation":
        return "Error: 'prompt' is required."

    prov = (provider or "").strip().lower()
    openai_key    = os.environ.get("OPENAI_API_KEY", "").strip()
    stability_key = os.environ.get("STABILITY_API_KEY", "").strip()

    if prov == "stability" or (not prov and stability_key and not openai_key):
        return _stability_generate(prompt, size, stability_key, filename)

    if prov == "openai" or (not prov and openai_key):
        return _dalle_call(action, prompt, image_path, mask_path,
                           size, quality, style, n, openai_key, filename)

    return (
        "Error: No image generation API key found.\n"
        "Set OPENAI_API_KEY or STABILITY_API_KEY in your .env file."
    )


# ──────────────────────────────────────────────────────────────────────────────
# DALL-E backend
# ──────────────────────────────────────────────────────────────────────────────

def _dalle_call(
    action: str,
    prompt: str,
    image_path: str,
    mask_path: str,
    size: str,
    quality: str,
    style: str,
    n: int,
    api_key: str,
    filename: str,
) -> str:
    if not api_key:
        return "Error: OPENAI_API_KEY is not set."
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        return "Error: openai package not installed. Run: pip install openai"

    client = OpenAI(api_key=api_key)
    n = max(1, min(n, 4))

    try:
        if action == "generate":
            resp = client.images.generate(
                model="dall-e-3",
                prompt=prompt[:4000],
                size=size,          # type: ignore[arg-type]
                quality=quality,    # type: ignore[arg-type]
                style=style,        # type: ignore[arg-type]
                n=1,  # DALL-E 3 only supports n=1
                response_format="b64_json",
            )
            images = [resp.data[0].b64_json]
            revised = resp.data[0].revised_prompt

        elif action == "edit":
            if not image_path:
                return "Error: 'image_path' is required for edit."
            src = _safe_path(image_path)
            if src is None:
                return "❌ Security: image_path is outside the project directory."
            with open(src, "rb") as f:
                img_data = f.read()
            mask_data = None
            if mask_path:
                mp = _safe_path(mask_path)
                if mp:
                    with open(mp, "rb") as f:
                        mask_data = f.read()
            resp = client.images.edit(
                model="dall-e-2",
                image=img_data,
                mask=mask_data,
                prompt=prompt[:1000],
                n=n,
                size=size,          # type: ignore[arg-type]
                response_format="b64_json",
            )
            images = [d.b64_json for d in resp.data]
            revised = None

        elif action == "variation":
            if not image_path:
                return "Error: 'image_path' is required for variation."
            src = _safe_path(image_path)
            if src is None:
                return "❌ Security: image_path is outside the project directory."
            with open(src, "rb") as f:
                img_data = f.read()
            resp = client.images.create_variation(
                model="dall-e-2",
                image=img_data,
                n=n,
                size=size,          # type: ignore[arg-type]
                response_format="b64_json",
            )
            images = [d.b64_json for d in resp.data]
            revised = None

        else:
            return f"Unknown action '{action}'. Use: generate, edit, variation."

        return _save_images(images, filename, revised, action)

    except Exception as exc:
        logger.error("image_gen_tool (DALL-E): %s", exc)
        return f"DALL-E error: {exc}"


def _save_images(images: list, filename: str, revised_prompt: str | None, action: str) -> str:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = str(int(time.time()))
    saved = []
    for i, b64 in enumerate(images):
        if b64 is None:
            continue
        base = filename or f"{action}_{stamp}"
        base = base.replace("/", "_").replace("\\", "_")
        fname = f"{base}_{i}.png" if len(images) > 1 else f"{base}.png"
        out = _OUTPUT_DIR / fname
        out.write_bytes(base64.b64decode(b64))
        saved.append(str(out))
    lines = [f"Generated {len(saved)} image(s):"] + [f"  • {p}" for p in saved]
    if revised_prompt:
        lines.append(f"\nRevised prompt: {revised_prompt}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Stability AI backend
# ──────────────────────────────────────────────────────────────────────────────

def _stability_generate(prompt: str, size: str, api_key: str, filename: str) -> str:
    if not api_key:
        return "Error: STABILITY_API_KEY is not set."
    import json as _json, urllib.request, urllib.error
    # Parse size (default 1024x1024)
    parts = size.split("x")
    width  = int(parts[0]) if len(parts) == 2 else 1024
    height = int(parts[1]) if len(parts) == 2 else 1024
    payload = {
        "text_prompts": [{"text": prompt, "weight": 1.0}],
        "width": width, "height": height,
        "steps": 30, "cfg_scale": 7,
        "samples": 1,
    }
    endpoint = "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image"
    body = _json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        endpoint, data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = _json.loads(resp.read())
        imgs = [art["base64"] for art in data.get("artifacts", []) if art.get("base64")]
        return _save_images(imgs, filename, None, "stable_diffusion")
    except urllib.error.HTTPError as exc:
        try:
            detail = _json.loads(exc.read())
            msg    = detail.get("message", str(exc))
        except Exception:
            msg = str(exc)
        return f"Stability AI error ({exc.code}): {msg}"
    except Exception as exc:
        return f"Stability AI error: {exc}"


def _safe_path(p: str) -> Path | None:
    path = Path(p)
    if not path.is_absolute():
        path = (_PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()
    pr = str(_PROJECT_ROOT)
    if str(path) == pr or str(path).startswith(pr + os.sep):
        return path
    return None
