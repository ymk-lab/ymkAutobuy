"""Longbridge credential / Config helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


REQUIRED_ENV = (
    "LONGBRIDGE_APP_KEY",
    "LONGBRIDGE_APP_SECRET",
    "LONGBRIDGE_ACCESS_TOKEN",
)


def load_dotenv_if_present(path: str | Path | None = None) -> bool:
    """Load a local `.env` into process env (does not override existing vars)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    if path is not None:
        return bool(load_dotenv(path, override=False))
    # Prefer repo-root .env when running from examples/ or src/
    here = Path.cwd()
    for candidate in (here / ".env", here.parent / ".env", Path(__file__).resolve().parents[3] / ".env"):
        if candidate.is_file():
            return bool(load_dotenv(candidate, override=False))
    return bool(load_dotenv(override=False))


def has_longbridge_credentials() -> bool:
    load_dotenv_if_present()
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

    load_dotenv_if_present()
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
