"""Outbound email through the company's own mailbox (SMTP, app password).

The sender is BRAND_FROM_EMAIL (an address on the company's domain); the
login is SMTP_USER / SMTP_PASSWORD on SMTP_HOST. `dry_run=True` (the default)
writes the complete message as an .eml under DATA_ROOT/outbox-dry instead of
connecting, and a test process can never send live unless
CCS_ALLOW_LIVE_MAIL_IN_TESTS is set. Every message carries SELF_HEADER so a
reader of the inbox can skip the suite's own sends.
"""
from __future__ import annotations

import os
import re
import smtplib
import sys
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Optional

from . import config, secrets

SELF_HEADER = "X-Convention-Social-Agent"
DEFAULT_SMTP_PORT = 587


@dataclass
class MailResult:
    sent: bool
    dry_run: bool
    path: Optional[Path] = None
    message_id: Optional[str] = None
    error: Optional[str] = None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "mail"


def build(subject: str, html: str, *, to: str, plain: Optional[str] = None,
          reply_to: Optional[str] = None, headers: Optional[dict[str, str]] = None,
          from_addr: Optional[str] = None, inline: Optional[dict[str, bytes]] = None,
          attachments: Optional[list[tuple[str, bytes, str]]] = None) -> EmailMessage:
    """`inline` maps a Content-ID (used in the HTML as src="cid:<id>") to JPEG bytes.
    `attachments` is a list of (filename, bytes, mime type)."""
    cfg = config.get_config()
    # long plain-ASCII headers (List-Unsubscribe) must not be folded into encoded words
    msg = EmailMessage(policy=policy.SMTP.clone(max_line_length=998))
    msg["Subject"] = subject
    msg["From"] = from_addr or cfg.brand_from_email
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=cfg.brand_domain or None)
    msg[SELF_HEADER] = "1"
    if reply_to:
        msg["Reply-To"] = reply_to
    for key, value in (headers or {}).items():
        msg[key] = value
    msg.set_content(plain or "This message is best viewed as HTML.")
    msg.add_alternative(html, subtype="html")
    if inline:
        html_part = msg.get_payload()[-1]
        for cid, data in inline.items():
            html_part.add_related(data, maintype="image", subtype="jpeg", cid=f"<{cid}>",
                                  disposition="inline", filename=f"{cid}.jpg")
    for filename, data, mime in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=filename)
    return msg


def in_test_process() -> bool:
    return "unittest" in sys.modules and not os.environ.get("CCS_ALLOW_LIVE_MAIL_IN_TESTS")


def send(subject: str, html: str, *, to: str, plain: Optional[str] = None,
         reply_to: Optional[str] = None, headers: Optional[dict[str, str]] = None,
         dry_run: bool = True, from_addr: Optional[str] = None,
         inline: Optional[dict[str, bytes]] = None,
         attachments: Optional[list[tuple[str, bytes, str]]] = None) -> MailResult:
    cfg = config.get_config()
    msg = build(subject, html, to=to, plain=plain, reply_to=reply_to, headers=headers,
                from_addr=from_addr, inline=inline, attachments=attachments)
    if dry_run or in_test_process():
        outbox = cfg.data_root / "outbox-dry"
        outbox.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        path = outbox / f"{stamp}-{_slug(subject)}.eml"
        path.write_bytes(bytes(msg))
        return MailResult(sent=False, dry_run=True, path=path, message_id=msg["Message-ID"])
    password = secrets.get_secret("SMTP_PASSWORD")
    if not (cfg.smtp_host and cfg.smtp_user and password and msg["From"]):
        return MailResult(sent=False, dry_run=False,
                          error="SMTP_HOST, SMTP_USER, SMTP_PASSWORD or BRAND_FROM_EMAIL missing")
    port = int(config.getenv("SMTP_PORT", str(DEFAULT_SMTP_PORT)) or DEFAULT_SMTP_PORT)
    try:
        with smtplib.SMTP(cfg.smtp_host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(cfg.smtp_user, password)
            server.send_message(msg)
        return MailResult(sent=True, dry_run=False, message_id=msg["Message-ID"])
    except Exception as e:  # noqa: BLE001
        return MailResult(sent=False, dry_run=False, error=f"{type(e).__name__}: {e}")
