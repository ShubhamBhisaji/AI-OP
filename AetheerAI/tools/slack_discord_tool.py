"""
slack_discord_tool — Send messages to Slack or Discord via incoming webhooks.

Env vars:
    SLACK_WEBHOOK_URL    — Incoming Webhook URL from api.slack.com/apps.
    DISCORD_WEBHOOK_URL  — Webhook URL from Discord Server Settings → Integrations.

Actions
-------
  slack    : Post a message to a Slack channel.
  discord  : Post a message to a Discord channel.
  notify   : Post to whichever webhook is configured (Slack first, then Discord).

Slack message features:
  • text    — plain message text (shown in notification previews).
  • title   — bold heading block (optional).
  • color   — hex sidebar color (default #3b82f6), e.g. "#ef4444" for red alerts.
  • fields  — JSON array of {"title": ..., "value": ...} for structured data.

Discord message features:
  • text    — message content.
  • title   — embed title (optional).
  • color   — decimal int or hex color string for the embed sidebar.
  • fields  — JSON array of {"name": ..., "value": ..., "inline": true/false}.
"""

from __future__ import annotations

import json as _json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_TIMEOUT = 10


def slack_discord_tool(
    action: str = "notify",
    text: str = "",
    title: str = "",
    color: str = "#3b82f6",
    fields: str = "",
    username: str = "AetheerAI",
    icon_emoji: str = ":zap:",
) -> str:
    """
    Send a notification to Slack or Discord.

    action      : slack | discord | notify
    text        : Main message body.
    title       : Optional bold heading for the message.
    color       : Hex color string for the message accent bar (default: blue).
    fields      : JSON array of extra data fields — see module docstring.
    username    : Sender display name (Slack only).
    icon_emoji  : Slack emoji for the bot icon (e.g. ':robot_face:').
    """
    if not text:
        return "Error: 'text' is required."

    action = (action or "notify").strip().lower()

    # Parse optional fields
    parsed_fields: list[dict] = []
    if fields and fields.strip():
        try:
            parsed_fields = _json.loads(fields)
            if not isinstance(parsed_fields, list):
                return "Error: 'fields' must be a JSON array."
        except Exception as e:
            return f"Error parsing fields JSON: {e}"

    slack_url   = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    discord_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

    results = []

    if action in ("slack", "notify"):
        if slack_url:
            r = _send_slack(slack_url, text, title, color, parsed_fields, username, icon_emoji)
            results.append(f"Slack: {r}")
        elif action == "slack":
            return "Error: SLACK_WEBHOOK_URL is not set in your .env file."

    if action in ("discord", "notify"):
        if discord_url:
            r = _send_discord(discord_url, text, title, color, parsed_fields, username)
            results.append(f"Discord: {r}")
        elif action == "discord":
            return "Error: DISCORD_WEBHOOK_URL is not set in your .env file."

    if not results:
        return (
            "Error: No webhook URL configured.\n"
            "Set SLACK_WEBHOOK_URL and/or DISCORD_WEBHOOK_URL in your .env file."
        )

    return "\n".join(results)


# ──────────────────────────────────────────────────────────────────────────────
# Slack
# ──────────────────────────────────────────────────────────────────────────────

def _send_slack(
    webhook_url: str,
    text: str,
    title: str,
    color: str,
    fields: list[dict],
    username: str,
    icon_emoji: str,
) -> str:
    blocks: list[dict] = []
    if title:
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": title, "emoji": True},
        })
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": text},
    })

    attachments: list[dict] = []
    if fields:
        attachment_fields = [
            {"title": f.get("title", ""), "value": f.get("value", ""), "short": True}
            for f in fields
        ]
        attachments.append({"color": color, "fields": attachment_fields})

    payload = {
        "text":        title or text,
        "username":    username,
        "icon_emoji":  icon_emoji,
        "blocks":      blocks,
    }
    if attachments:
        payload["attachments"] = attachments

    return _post_json(webhook_url, payload)


# ──────────────────────────────────────────────────────────────────────────────
# Discord
# ──────────────────────────────────────────────────────────────────────────────

def _send_discord(
    webhook_url: str,
    text: str,
    title: str,
    color: str,
    fields: list[dict],
    username: str,
) -> str:
    # Convert color to decimal int for Discord
    color_int = 0x3B82F6  # default blue
    try:
        if color.startswith("#"):
            color_int = int(color.lstrip("#"), 16)
        else:
            color_int = int(color)
    except Exception:
        pass

    discord_fields = [
        {
            "name":   f.get("name") or f.get("title", "Field"),
            "value":  f.get("value", ""),
            "inline": f.get("inline", False),
        }
        for f in fields
    ]

    embed: dict = {"description": text, "color": color_int}
    if title:
        embed["title"] = title
    if discord_fields:
        embed["fields"] = discord_fields

    payload: dict = {
        "username": username,
        "embeds":   [embed],
    }

    return _post_json(webhook_url, payload)


# ──────────────────────────────────────────────────────────────────────────────
# Shared HTTP helper
# ──────────────────────────────────────────────────────────────────────────────

def _post_json(url: str, payload: dict) -> str:
    # SSRF guard — only allow HTTPS
    if not url.startswith("https://"):
        return "Blocked: webhook URL must use HTTPS."
    body = _json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "AetheerAI/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            status = resp.status
        if status in (200, 204):
            return "Message sent successfully."
        return f"Unexpected status: {status}"
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        return f"HTTP {exc.code}: {detail[:300]}"
    except Exception as exc:
        logger.error("slack_discord_tool: %s", exc)
        return f"Error: {exc}"
