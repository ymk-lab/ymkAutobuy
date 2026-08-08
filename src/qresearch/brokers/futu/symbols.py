"""Futu / qresearch symbol helpers.

Futu OpenD uses ``US.AAPL``; qresearch uses ``AAPL.US``.
"""

from __future__ import annotations


def to_futu_code(symbol: str, *, default_market: str = "US") -> str:
    s = str(symbol).strip().upper()
    if not s:
        raise ValueError("empty symbol")
    if "." in s:
        left, right = s.split(".", 1)
        # AAPL.US → US.AAPL ; US.AAPL stays
        if left in {"US", "HK", "SH", "SZ"} and right:
            return f"{left}.{right}"
        if right in {"US", "HK", "SH", "SZ"}:
            return f"{right}.{left}"
    mkt = default_market.upper()
    return f"{mkt}.{s}"


def from_futu_code(code: str) -> str:
    s = str(code).strip().upper()
    if "." not in s:
        return f"{s}.US"
    left, right = s.split(".", 1)
    if left in {"US", "HK", "SH", "SZ"}:
        return f"{right}.{left}"
    if right in {"US", "HK", "SH", "SZ"}:
        return f"{left}.{right}"
    return f"{s}.US"


def normalize_symbol(symbol: str, *, default_market: str = "US") -> str:
    """Normalize to ``TICKER.MARKET`` (qresearch form)."""
    return from_futu_code(to_futu_code(symbol, default_market=default_market))
