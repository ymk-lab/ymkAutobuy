"""Fetch daily OHLCV via Futu OpenD."""

from __future__ import annotations

from datetime import date, datetime, timedelta
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
    max_count: int = 1000,
    last_error: list[str] | None = None,
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
            max_count=int(max_count),
            page_req_key=page_key,
        )
        if ret != RET_OK:
            if last_error is not None:
                last_error.append(str(data))
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
    except Exception as exc:
        if last_error is not None:
            last_error.append(f"convert:{exc}")
        return None


def fetch_daily_resilient(
    quote_ctx: Any,
    symbol: str,
    *,
    start: date | str = date(2021, 6, 1),
    end: date | str | None = None,
    default_market: str = "US",
    min_bars: int = 220,
) -> tuple[pd.DataFrame | None, str]:
    """Try long history, then shorter windows. Returns ``(df, note)``."""
    end_d = date.fromisoformat(str(end or date.today())[:10])
    start0 = date.fromisoformat(str(start)[:10])
    attempts: list[tuple[date, int]] = [
        (start0, 1000),
        (date(end_d.year - 2, end_d.month, end_d.day), 1000),  # ~2y
        (end_d - timedelta(days=400), 1000),
        (date(2024, 1, 1), 1000),
    ]
    # de-dupe starts
    seen: set[str] = set()
    last_err: list[str] = []
    best: pd.DataFrame | None = None
    note = "empty"
    for st, mc in attempts:
        key = str(st)
        if key in seen or st > end_d:
            continue
        seen.add(key)
        err: list[str] = []
        df = fetch_daily(
            quote_ctx,
            symbol,
            start=st,
            end=end_d,
            default_market=default_market,
            max_count=mc,
            last_error=err,
        )
        if err:
            last_err = err
        if df is None or len(df) == 0:
            continue
        if best is None or len(df) > len(best):
            best = df
            note = f"start={st} bars={len(df)}"
        if len(df) >= min_bars:
            return df, note
    if best is not None:
        return best, note + (f" err={last_err[-1]}" if last_err else "")
    return None, (last_err[-1] if last_err else "no_rows")
