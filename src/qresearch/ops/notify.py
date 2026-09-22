"""Email alerts for Freeze / Once failure. Logs if SMTP is not configured."""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Iterable


def alert(subject: str, body: str) -> bool:
    to_addr = (os.getenv("QRESEARCH_ALERT_TO") or "").strip()
    if not to_addr:
        print(f"ALERT (no QRESEARCH_ALERT_TO): {subject}\n{body}", flush=True)
        return False
    from_addr = (os.getenv("QRESEARCH_ALERT_FROM") or to_addr).strip()
    host = (os.getenv("QRESEARCH_SMTP_HOST") or "").strip()
    if not host:
        print(f"ALERT (no SMTP): to={to_addr} {subject}\n{body}", flush=True)
        return False
    port = int(os.getenv("QRESEARCH_SMTP_PORT") or "587")
    user = (os.getenv("QRESEARCH_SMTP_USER") or "").strip()
    password = os.getenv("QRESEARCH_SMTP_PASSWORD") or ""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)
    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.starttls(context=ctx)
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)
    return True


def freeze_alert(reason: str, extra: Iterable[str] | None = None) -> None:
    lines = [reason, *(extra or ())]
    try:
        alert("qresearch Freeze", "\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        print(f"ALERT send failed: {exc}", flush=True)
