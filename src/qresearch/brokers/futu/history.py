"""Fetch daily OHLCV via Futu OpenD."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from qresearch.brokers.futu.symbols import to_futu_code
from qresearch.data.loader import validate_ohlcv


def history_kline_to_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Convert Futu ``get_history_kline`` frame to validated OHLCV."""
    if df is None or len(df) == 0:
        raise ValueError("empty kline frame")
    out = pd.DataFrame(
        {
            "open": df["open"].astype(float),
            "high": df["high"].astype(float),
            "low": df["low"].astype(float),
            "close": df["close"].astype(float),
            "volume": df["volume"].astype(float),
        }
    )
    # time_key like 2024-01-02 00:00:00
    if "time_key" in df.columns:
        out.index = pd.to_datetime(df["time_key"]).tz_localize(None).normalize()
    else:
        out.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return validate_ohlcv(out)


def fetch_daily(
    quote_ctx: Any,
    symbol: str,
    *,
    start: date | str,
    end: date | str | None = None,
    default_market: str = "US",
) -> pd.DataFrame | None:
    from futu import AuType, KLType, RET_OK

    code = to_futu_code(symbol, default_market=default_market)
    start_s = str(start)[:10]
    end_s = str(end or date.today())[:10]
    frames: list[pd.DataFrame] = []
    page_key = None
    while True:
        ret, data, page_key = quote_ctx.request_history_kline(
            code,
            start=start_s,
            end=end_s,
            ktype=KLType.K_DAY,
            autype=AuType.QFQ,
            max_count=1000,
            page_req_key=page_key,
        )
        if ret != RET_OK:
            break
        if data is None or len(data) == 0:
            break
        frames.append(data)
        if page_key is None:
            break
    if not frames:
        return None
    try:
        return history_kline_to_ohlcv(pd.concat(frames, ignore_index=True))
    except Exception:
        return None
