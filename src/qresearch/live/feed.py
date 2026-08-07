"""Market data feed abstractions for the live loop."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator

import pandas as pd

from qresearch.data.panel import align_panel


@dataclass(frozen=True)
class Bar:
    timestamp: pd.Timestamp
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketDataFeed(ABC):
    """Yields synchronized multi-symbol bar maps keyed by symbol."""

    @abstractmethod
    def __iter__(self) -> Iterator[dict[str, Bar]]:
        raise NotImplementedError


class HistoricalReplayFeed(MarketDataFeed):
    """Replay an OHLCV panel as if it were a live bar stream."""

    def __init__(self, panel: dict[str, pd.DataFrame]) -> None:
        self.panel = align_panel(panel)
        self.symbols = list(self.panel.keys())
        self.index = next(iter(self.panel.values())).index

    def __iter__(self) -> Iterator[dict[str, Bar]]:
        for ts in self.index:
            batch: dict[str, Bar] = {}
            for sym, df in self.panel.items():
                row = df.loc[ts]
                batch[sym] = Bar(
                    timestamp=pd.Timestamp(ts),
                    symbol=sym,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            yield batch
