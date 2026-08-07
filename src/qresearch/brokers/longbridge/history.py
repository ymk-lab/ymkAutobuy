"""Pull Longbridge candlesticks into a qresearch OHLCV panel."""

from __future__ import annotations

from typing import Any

import pandas as pd

from qresearch.brokers.longbridge.symbols import normalize_symbol
from qresearch.data.loader import validate_ohlcv
from qresearch.data.panel import align_panel


def candlesticks_to_ohlcv(candles: list[Any]) -> pd.DataFrame:
    rows = []
    for c in candles:
        rows.append(
            {
                "datetime": pd.Timestamp(getattr(c, "timestamp")),
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": float(getattr(c, "volume", 0) or 0),
            }
        )
    if not rows:
        raise ValueError("no candlesticks returned")
    df = pd.DataFrame(rows).set_index("datetime").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return validate_ohlcv(df)


def load_longbridge_panel(
    symbols: list[str],
    *,
    quote_ctx: Any | None = None,
    count: int = 300,
    period: Any | None = None,
    adjust: Any | None = None,
    default_market: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Fetch recent daily (or other period) bars for each symbol."""
    try:
        from longbridge.openapi import AdjustType, Period, QuoteContext
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "longbridge SDK not installed. Install with: pip install 'qresearch[longbridge]'"
        ) from exc

    if quote_ctx is None:
        from qresearch.brokers.longbridge.config import load_longbridge_config

        quote_ctx = QuoteContext(load_longbridge_config())

    period = period or Period.Day
    adjust = adjust or AdjustType.NoAdjust

    frames: dict[str, pd.DataFrame] = {}
    for raw in symbols:
        sym = normalize_symbol(raw, default_market=default_market)
        candles = quote_ctx.candlesticks(sym, period, int(count), adjust)
        frames[sym] = candlesticks_to_ohlcv(list(candles))
    return align_panel(frames)
