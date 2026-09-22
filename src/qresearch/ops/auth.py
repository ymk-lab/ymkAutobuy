"""Token + Confirm Action for the web cockpit."""

from __future__ import annotations

import hmac
import os

from qresearch.ops.control import CONFIRM_PHRASE


def ui_token() -> str:
    return (os.getenv("QRESEARCH_UI_TOKEN") or "").strip()


def token_ok(provided: str | None) -> bool:
    expected = ui_token()
    if not expected:
        return True
    got = (provided or "").strip()
    if got.lower().startswith("bearer "):
        got = got[7:].strip()
    return hmac.compare_digest(got, expected)


def confirm_ok(provided: str | None) -> bool:
    got = (provided or "").strip()
    return hmac.compare_digest(got, CONFIRM_PHRASE)
