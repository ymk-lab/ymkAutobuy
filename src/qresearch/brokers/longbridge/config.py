"""Longbridge credential / Config helpers."""

from __future__ import annotations

import os
from typing import Any


REQUIRED_ENV = (
    "LONGBRIDGE_APP_KEY",
    "LONGBRIDGE_APP_SECRET",
    "LONGBRIDGE_ACCESS_TOKEN",
)


def has_longbridge_credentials() -> bool:
    return all(os.getenv(k) for k in REQUIRED_ENV)


def load_longbridge_config(
    *,
    app_key: str | None = None,
    app_secret: str | None = None,
    access_token: str | None = None,
) -> Any:
    """Create a Longbridge `Config`.

    Prefer explicit args; otherwise use `Config.from_apikey_env()` which also
    loads a local `.env` file when present.
    """
    try:
        from longbridge.openapi import Config
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "longbridge SDK not installed. Install with: pip install 'qresearch[longbridge]'"
        ) from exc

    if app_key and app_secret and access_token:
        return Config.from_apikey(app_key, app_secret, access_token)
    if not has_longbridge_credentials():
        missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
        raise EnvironmentError(
            "Missing Longbridge credentials: "
            + ", ".join(missing)
            + ". Set env vars or pass app_key/app_secret/access_token."
        )
    return Config.from_apikey_env()
