"""Meta webhook verification and callback intake routes."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse


logger = logging.getLogger("aetheer.api.meta_webhook")

router = APIRouter(prefix="/api/meta", tags=["Integrations"])


def _env_text(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _is_valid_signature(body: bytes, *, received: str, secret: str) -> bool:
    raw_signature = str(received or "").strip()
    if not raw_signature.startswith("sha256="):
        return False

    received_hash = raw_signature.split("=", 1)[1].strip().lower()
    if not received_hash:
        return False

    expected_hash = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(received_hash, expected_hash)


@router.get("/webhook", response_class=PlainTextResponse)
def verify_meta_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    configured_verify_token = _env_text("META_WEBHOOK_VERIFY_TOKEN")
    if not configured_verify_token:
        raise HTTPException(status_code=503, detail="META_WEBHOOK_VERIFY_TOKEN is not configured")

    if (hub_mode or "").strip().lower() != "subscribe":
        raise HTTPException(status_code=400, detail="hub.mode must be subscribe")

    presented_verify_token = (hub_verify_token or "").strip()
    if not hmac.compare_digest(presented_verify_token, configured_verify_token):
        raise HTTPException(status_code=403, detail="Webhook verify token mismatch")

    if hub_challenge is None:
        raise HTTPException(status_code=400, detail="hub.challenge is required")

    return PlainTextResponse(content=str(hub_challenge), status_code=200)


@router.post("/webhook", response_class=PlainTextResponse)
async def receive_meta_webhook(request: Request) -> PlainTextResponse:
    raw_body = await request.body()
    configured_app_secret = _env_text("META_APP_SECRET")

    if configured_app_secret:
        received_signature = (request.headers.get("X-Hub-Signature-256") or "").strip()
        if not received_signature:
            raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")

        if not _is_valid_signature(
            raw_body,
            received=received_signature,
            secret=configured_app_secret,
        ):
            raise HTTPException(status_code=401, detail="Invalid X-Hub-Signature-256 header")

    payload: dict[str, Any] = {}
    if raw_body:
        try:
            decoded = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Webhook body must be valid JSON") from exc

        if isinstance(decoded, dict):
            payload = decoded
        else:
            raise HTTPException(status_code=400, detail="Webhook body must be a JSON object")

    object_type = str(payload.get("object") or "unknown")
    entries = payload.get("entry")
    entry_count = len(entries) if isinstance(entries, list) else 0

    logger.info(
        "Meta webhook event received (object=%s entries=%s)",
        object_type,
        entry_count,
    )
    return PlainTextResponse(content="EVENT_RECEIVED", status_code=200)
