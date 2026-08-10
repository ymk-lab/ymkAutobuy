"""Fetch RTH 09:40 ET entry prices (paper / research)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from qresearch.brokers.futu.symbols import normalize_symbol, to_futu_code

ET = ZoneInfo("America/New_York")


def _bar_open_at(
    raw: pd.DataFrame,
    *,
    day: date,
    hour: int,
    minute: int,
) -> float | None:
    if raw is None or len(raw) == 0 or "time_key" not in raw.columns:
        return None
    ts = pd.to_datetime(raw["time_key"])
    if getattr(ts.dt, "tz", None) is None:
        # Futu US intraday keys are typically Eastern wall-clock.
        ts = ts.dt.tz_localize(ET, ambiguous="infer", nonexistent="shift_forward")
    else:
        ts = ts.dt.tz_convert(ET)
    target = pd.Timestamp(datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET))
    hit = raw.loc[ts == target]
    if len(hit) == 0:
        # nearest within 2 minutes
        delta = (ts - target).abs()
        i = int(delta.argmin())
        if delta.iloc[i] <= pd.Timedelta(minutes=2):
            return float(raw.iloc[i]["open"])
        return None
    return float(hit.iloc[0]["open"])


def fetch_0940_open_futu(
    quote_ctx: Any,
    symbols: list[str],
    *,
    day: date | None = None,
    default_market: str = "US",
) -> dict[str, float]:
    """Return ``TICKER.US → 09:40 open`` via Futu 1m (fallback 5m)."""
    from futu import AuType, KLType, RET_OK

    day = day or datetime.now(ET).date()
    start = str(day)
    end = str(day)
    out: dict[str, float] = {}
    for sym in symbols:
        code = to_futu_code(sym, default_market=default_market)
        px = None
        for ktype in (KLType.K_1M, KLType.K_5M):
            ret, data, _ = quote_ctx.request_history_kline(
                code,
                start=start,
                end=end,
                ktype=ktype,
                autype=AuType.NONE,
                max_count=1000,
            )
            if ret != RET_OK or data is None or len(data) == 0:
                continue
            px = _bar_open_at(data, day=day, hour=9, minute=40)
            if px is not None:
                break
        if px is not None:
            out[normalize_symbol(sym, default_market=default_market)] = px
    return out


def fetch_0940_open_yahoo(
    symbols: list[str],
    *,
    day: date | None = None,
) -> dict[str, float]:
    """Yahoo 5m/1m fallback for 09:40 open (recent sessions only)."""
    import yfinance as yf

    day = day or datetime.now(ET).date()
    out: dict[str, float] = {}
    for sym in symbols:
        bare = str(sym).split(".")[0].upper()
        px = None
        for interval in ("1m", "5m"):
            try:
                raw = yf.Ticker(bare).history(
                    period="7d" if interval == "5m" else "5d",
                    interval=interval,
                    auto_adjust=False,
                )
            except Exception:
                continue
            if raw is None or raw.empty:
                continue
            idx = raw.index
            if idx.tz is None:
                idx = idx.tz_localize(ET)
            else:
                idx = idx.tz_convert(ET)
            raw = raw.copy()
            raw.index = idx
            target = pd.Timestamp(datetime(day.year, day.month, day.day, 9, 40, tzinfo=ET))
            if target in raw.index:
                px = float(raw.loc[target, "Open"])
                break
            day_mask = [i.date() == day for i in raw.index]
            day_bars = raw.loc[day_mask]
            if len(day_bars) == 0:
                continue
            deltas = abs(day_bars.index - target)
            j = int(deltas.argmin())
            if deltas[j] <= pd.Timedelta(minutes=2):
                px = float(day_bars.iloc[j]["Open"])
                break
        if px is not None:
            out[normalize_symbol(bare)] = px
    return out


def resolve_0940_marks(
    symbols: list[str],
    *,
    quote_ctx: Any | None = None,
    day: date | None = None,
    default_market: str = "US",
) -> tuple[dict[str, float], str]:
    """Prefer Futu intraday; fall back to Yahoo. Returns (marks, source)."""
    day = day or datetime.now(ET).date()
    marks: dict[str, float] = {}
    source = "none"
    if quote_ctx is not None:
        try:
            marks = fetch_0940_open_futu(
                quote_ctx, symbols, day=day, default_market=default_market
            )
            if marks:
                source = "futu_0940"
        except Exception:
            marks = {}
    missing = [
        normalize_symbol(s, default_market=default_market)
        for s in symbols
        if normalize_symbol(s, default_market=default_market) not in marks
    ]
    if missing:
        try:
            y = fetch_0940_open_yahoo(missing, day=day)
            marks.update(y)
            if y and source == "none":
                source = "yahoo_0940"
            elif y and source.startswith("futu"):
                source = "futu_0940+yahoo"
        except Exception:
            pass
    return marks, source
