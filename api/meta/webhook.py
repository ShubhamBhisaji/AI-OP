"""Vercel serverless Meta webhook endpoint (stdlib only)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _text_response(handler: BaseHTTPRequestHandler, status: int, body: str) -> None:
    encoded = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _verify_signature(raw_body: bytes, signature_header: str, app_secret: str) -> bool:
    signature = str(signature_header or "").strip()
    if not signature.startswith("sha256="):
        return False
    received_hash = signature.split("=", 1)[1].strip().lower()
    if not received_hash:
        return False

    expected_hash = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(received_hash, expected_hash)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        verify_token = _env("META_WEBHOOK_VERIFY_TOKEN")
        if not verify_token:
            _json_response(self, 503, {"error": "META_WEBHOOK_VERIFY_TOKEN is not configured"})
            return

        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        mode = (query.get("hub.mode", [""])[0] or "").strip().lower()
        token = (query.get("hub.verify_token", [""])[0] or "").strip()
        challenge = query.get("hub.challenge", [None])[0]

        if mode != "subscribe":
            _json_response(self, 400, {"error": "hub.mode must be subscribe"})
            return

        if not hmac.compare_digest(token, verify_token):
            _json_response(self, 403, {"error": "Webhook verify token mismatch"})
            return

        if challenge is None:
            _json_response(self, 400, {"error": "hub.challenge is required"})
            return

        _text_response(self, 200, str(challenge))

    def do_POST(self) -> None:  # noqa: N802
        content_length = 0
        try:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            content_length = 0

        raw_body = self.rfile.read(max(0, content_length)) if content_length > 0 else b""
        app_secret = _env("META_APP_SECRET")

        if app_secret:
            signature = self.headers.get("X-Hub-Signature-256") or ""
            if not signature:
                _json_response(self, 401, {"error": "Missing X-Hub-Signature-256 header"})
                return

            if not _verify_signature(raw_body, signature, app_secret):
                _json_response(self, 401, {"error": "Invalid X-Hub-Signature-256 header"})
                return

        if raw_body:
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                _json_response(self, 400, {"error": "Webhook body must be valid JSON"})
                return
            if not isinstance(payload, dict):
                _json_response(self, 400, {"error": "Webhook body must be a JSON object"})
                return

        _text_response(self, 200, "EVENT_RECEIVED")
