"""Symbol helpers for Longbridge `TICKER.MARKET` format."""

from __future__ import annotations


def normalize_symbol(symbol: str, *, default_market: str | None = None) -> str:
    """Normalize to Longbridge symbol form, e.g. `AAPL.US`, `700.HK`."""
    sym = str(symbol).strip().upper()
    if not sym:
        raise ValueError("empty symbol")
    if "." in sym:
        ticker, market = sym.rsplit(".", 1)
        if not ticker or not market:
            raise ValueError(f"invalid symbol: {symbol}")
        return f"{ticker}.{market}"
    if default_market:
        return f"{sym}.{default_market.upper()}"
    raise ValueError(
        f"symbol '{symbol}' missing market suffix; use TICKER.MARKET (e.g. 700.HK)"
    )
