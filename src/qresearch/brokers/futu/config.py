"""Futu OpenD connection helpers."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv_if_present(path: str | Path | None = None) -> bool:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    if path is not None:
        return bool(load_dotenv(path, override=False))
    here = Path.cwd()
    for candidate in (
        here / ".env",
        here.parent / ".env",
        Path(__file__).resolve().parents[3] / ".env",
    ):
        if candidate.is_file():
            return bool(load_dotenv(candidate, override=False))
    return bool(load_dotenv(override=False))


def futu_opend_host() -> str:
    load_dotenv_if_present()
    return os.getenv("FUTU_OPEND_HOST", "127.0.0.1").strip() or "127.0.0.1"


def futu_opend_port() -> int:
    load_dotenv_if_present()
    return int(os.getenv("FUTU_OPEND_PORT", "11111"))


def futu_trd_env_simulate() -> bool:
    """True = paper (SIMULATE). Default True for safety."""
    load_dotenv_if_present()
    raw = os.getenv("FUTU_TRD_ENV", "SIMULATE").strip().upper()
    return raw in {"SIMULATE", "SIM", "PAPER", "1", "TRUE"}


def has_futu_opend() -> bool:
    """Best-effort TCP check that OpenD is listening."""
    import socket

    host, port = futu_opend_host(), futu_opend_port()
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False
