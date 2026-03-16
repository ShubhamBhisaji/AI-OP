"""
email_tool — Read and send emails via SMTP (outbound) and IMAP (inbox).

Env vars:
    EMAIL_ADDRESS   — Sender / login address (e.g. you@gmail.com).
    EMAIL_PASSWORD  — App password (NOT your main password — use an App Password).
    SMTP_HOST       — SMTP server (default: smtp.gmail.com).
    SMTP_PORT       — SMTP port (default: 587, uses STARTTLS).
    IMAP_HOST       — IMAP server (default: imap.gmail.com).
    IMAP_PORT       — IMAP port (default: 993, uses SSL).

Gmail quick-start:
    1. Enable 2-factor auth on your Google account.
    2. Go to https://myaccount.google.com/apppasswords → generate an App Password.
    3. Set EMAIL_ADDRESS and EMAIL_PASSWORD in your .env file.

Actions
-------
  send        : Send a plain-text or HTML email.
  read_inbox  : List recent unread emails (subject + sender + date).
  read_email  : Read the full body of a specific email by ID.
  reply       : Reply to an email by its Message-ID.
  search      : Search the inbox for emails matching a query string.
"""

from __future__ import annotations

import email as _email_lib
import imaplib
import logging
import os
import smtplib
import email.mime.multipart
import email.mime.text
from email.header import decode_header
from email.utils import formatdate

logger = logging.getLogger(__name__)

_DEFAULT_SMTP_HOST = "smtp.gmail.com"
_DEFAULT_SMTP_PORT = 587
_DEFAULT_IMAP_HOST = "imap.gmail.com"
_DEFAULT_IMAP_PORT = 993
_MAX_EMAILS        = 20


def email_tool(
    action: str,
    to: str = "",
    subject: str = "",
    body: str = "",
    html: bool = False,
    cc: str = "",
    email_id: str = "",
    query: str = "",
    folder: str = "INBOX",
    limit: int = 10,
    in_reply_to: str = "",
) -> str:
    """
    Manage email: send, read, reply, and search.

    action      : send | read_inbox | read_email | reply | search
    to          : Recipient address(es), comma-separated, for 'send'/'reply'.
    subject     : Email subject for 'send'.
    body        : Email body text (plain text or HTML).
    html        : Set True to send body as HTML (default: False).
    cc          : CC address(es), comma-separated.
    email_id    : UID string for 'read_email'.
    query       : IMAP search query for 'search' (e.g. 'FROM "boss@company.com"').
    folder      : IMAP folder name (default: INBOX).
    limit       : Max emails to return for read_inbox/search (max 20).
    in_reply_to : Message-ID of the email being replied to.
    """
    addr     = os.environ.get("EMAIL_ADDRESS", "").strip()
    password = os.environ.get("EMAIL_PASSWORD", "").strip()
    if not addr or not password:
        return (
            "Error: EMAIL_ADDRESS and EMAIL_PASSWORD must be set in your .env file.\n"
            "For Gmail, use an App Password (not your account password)."
        )

    smtp_host = os.environ.get("SMTP_HOST", _DEFAULT_SMTP_HOST)
    smtp_port = int(os.environ.get("SMTP_PORT", _DEFAULT_SMTP_PORT))
    imap_host = os.environ.get("IMAP_HOST", _DEFAULT_IMAP_HOST)
    imap_port = int(os.environ.get("IMAP_PORT", _DEFAULT_IMAP_PORT))

    action = (action or "").strip().lower()
    limit  = max(1, min(limit, _MAX_EMAILS))

    if action == "send":
        return _send_email(addr, password, smtp_host, smtp_port,
                           to, subject, body, html, cc, in_reply_to)

    if action in ("read_inbox", "search"):
        imap_query = query if action == "search" else "UNSEEN"
        return _read_inbox(addr, password, imap_host, imap_port,
                           folder, imap_query, limit)

    if action == "read_email":
        if not email_id:
            return "Error: 'email_id' is required for read_email."
        return _read_single(addr, password, imap_host, imap_port, folder, email_id)

    if action == "reply":
        if not in_reply_to:
            return "Error: 'in_reply_to' (Message-ID) is required for reply."
        return _send_email(addr, password, smtp_host, smtp_port,
                           to, f"Re: {subject}", body, html, cc, in_reply_to)

    return f"Unknown action '{action}'. Use: send, read_inbox, read_email, reply, search."


# ──────────────────────────────────────────────────────────────────────────────
# SMTP send
# ──────────────────────────────────────────────────────────────────────────────

def _send_email(
    addr: str, password: str,
    smtp_host: str, smtp_port: int,
    to: str, subject: str, body: str, html: bool,
    cc: str, in_reply_to: str,
) -> str:
    if not to:
        return "Error: 'to' (recipient) is required for send."
    if not subject:
        return "Error: 'subject' is required for send."
    if not body:
        return "Error: 'body' is required for send."

    # Validate recipients (basic check)
    recipients = [r.strip() for r in to.split(",") if r.strip()]
    if not recipients:
        return "Error: No valid recipient addresses in 'to'."

    msg = email.mime.multipart.MIMEMultipart("alternative")
    msg["From"]    = addr
    msg["To"]      = ", ".join(recipients)
    msg["Subject"] = subject
    msg["Date"]    = formatdate(localtime=True)
    if cc:
        cc_list       = [c.strip() for c in cc.split(",") if c.strip()]
        msg["Cc"]     = ", ".join(cc_list)
        recipients   += cc_list
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"]  = in_reply_to

    mime_type = "html" if html else "plain"
    msg.attach(email.mime.text.MIMEText(body, mime_type, "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(addr, password)
            server.sendmail(addr, recipients, msg.as_string())
        return f"Email sent to {', '.join(recipients)}. Subject: {subject}"
    except smtplib.SMTPAuthenticationError:
        return (
            "Error: SMTP authentication failed.\n"
            "For Gmail, ensure you are using an App Password, not your account password."
        )
    except Exception as exc:
        logger.error("email_tool (send): %s", exc)
        return f"SMTP error: {exc}"


# ──────────────────────────────────────────────────────────────────────────────
# IMAP read
# ──────────────────────────────────────────────────────────────────────────────

def _imap_connect(addr: str, password: str, imap_host: str, imap_port: int) -> imaplib.IMAP4_SSL:
    m = imaplib.IMAP4_SSL(imap_host, imap_port)
    m.login(addr, password)
    return m


def _decode_header_value(value: str) -> str:
    parts = decode_header(value)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _read_inbox(
    addr: str, password: str,
    imap_host: str, imap_port: int,
    folder: str, query: str, limit: int,
) -> str:
    try:
        m = _imap_connect(addr, password, imap_host, imap_port)
        m.select(f'"{folder}"')
        status, data = m.search(None, query)
        if status != "OK":
            m.logout()
            return f"IMAP search failed: {status}"
        uids = data[0].split()
        uids = uids[-limit:]  # most recent
        if not uids:
            m.logout()
            return f"No emails matching '{query}' in {folder}."

        lines = [f"Emails ({query}) in {folder}:"]
        for uid in reversed(uids):
            status, msg_data = m.fetch(uid, "(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if status != "OK":
                continue
            raw = msg_data[0][1] if msg_data and msg_data[0] else b""
            msg = _email_lib.message_from_bytes(raw)
            frm  = _decode_header_value(msg.get("From", ""))
            subj = _decode_header_value(msg.get("Subject", "(no subject)"))
            date = msg.get("Date", "")
            lines.append(f"  [{uid.decode()}] {date}  From: {frm}  Subject: {subj}")
        m.logout()
        return "\n".join(lines)
    except imaplib.IMAP4.error as exc:
        return f"IMAP error: {exc}"
    except Exception as exc:
        logger.error("email_tool (read_inbox): %s", exc)
        return f"Error: {exc}"


def _read_single(
    addr: str, password: str,
    imap_host: str, imap_port: int,
    folder: str, email_id: str,
) -> str:
    try:
        m = _imap_connect(addr, password, imap_host, imap_port)
        m.select(f'"{folder}"')
        status, msg_data = m.fetch(email_id.encode(), "(RFC822)")
        if status != "OK" or not msg_data or not msg_data[0]:
            m.logout()
            return f"Email ID '{email_id}' not found."
        raw = msg_data[0][1]
        msg = _email_lib.message_from_bytes(raw)
        frm  = _decode_header_value(msg.get("From", ""))
        subj = _decode_header_value(msg.get("Subject", "(no subject)"))
        date = msg.get("Date", "")
        mid  = msg.get("Message-ID", "")

        # Extract body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/plain" and not part.get("Content-Disposition"):
                    body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    break
        else:
            payload = msg.get_payload(decode=True)
            body = payload.decode("utf-8", errors="replace") if payload else ""

        m.logout()
        return (
            f"From       : {frm}\n"
            f"Date       : {date}\n"
            f"Subject    : {subj}\n"
            f"Message-ID : {mid}\n"
            f"{'─'*60}\n"
            f"{body[:5000]}"
            + ("\n[Truncated]" if len(body) > 5000 else "")
        )
    except Exception as exc:
        logger.error("email_tool (read_single): %s", exc)
        return f"Error: {exc}"
