"""Longbridge market-data feeds for the live loop."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterator

import pandas as pd

from qresearch.brokers.longbridge.symbols import normalize_symbol
from qresearch.live.feed import Bar, MarketDataFeed


@dataclass
class LongbridgePollingFeed(MarketDataFeed):
    """Poll `QuoteContext.quote` and emit synchronized bar snapshots.

    Each poll becomes one bar event. OHLC are approximated from the latest quote
    (`open`/`high`/`low`/`last_done`). Suitable for wiring live loops; for research
    backtests prefer `load_longbridge_panel`.
    """

    symbols: list[str]
    quote_ctx: Any
    interval_sec: float = 5.0
    max_bars: int | None = None
    default_market: str | None = None

    def __post_init__(self) -> None:
        self.symbols = [
            normalize_symbol(s, default_market=self.default_market) for s in self.symbols
        ]

    def __iter__(self) -> Iterator[dict[str, Bar]]:
        n = 0
        while self.max_bars is None or n < self.max_bars:
            quotes = self.quote_ctx.quote(self.symbols)
            batch: dict[str, Bar] = {}
            ts = pd.Timestamp.now("UTC").tz_convert(None)
            for q in quotes:
                sym = normalize_symbol(q.symbol, default_market=self.default_market)
                last = float(getattr(q, "last_done", 0) or 0)
                open_ = float(getattr(q, "open", last) or last)
                high = float(getattr(q, "high", last) or last)
                low = float(getattr(q, "low", last) or last)
                if last <= 0:
                    continue
                q_ts = getattr(q, "timestamp", None)
                bar_ts = pd.Timestamp(q_ts) if q_ts is not None else ts
                batch[sym] = Bar(
                    timestamp=bar_ts,
                    symbol=sym,
                    open=open_,
                    high=high,
                    low=low,
                    close=last,
                    volume=float(getattr(q, "volume", 0) or 0),
                )
            if batch:
                n += 1
                yield batch
            if self.max_bars is not None and n >= self.max_bars:
                break
            time.sleep(max(self.interval_sec, 0.01))
