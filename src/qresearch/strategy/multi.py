"""Multi-asset strategy interfaces and examples."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

from qresearch.data.panel import panel_close
from qresearch.strategy.base import Strategy


class MultiAssetStrategy(ABC):
    """Strategy that emits a wide signal matrix (columns = symbols)."""

    name: str = "multi_strategy"

    @abstractmethod
    def generate_signals(self, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        raise NotImplementedError


@dataclass
class CrossSectionalMomentumStrategy(MultiAssetStrategy):
    """Long top momentum names (optional short bottom).

    Signal values are ranks mapped to [-1, 1] or [0, 1].
    """

    lookback: int = 20
    top_fraction: float = 0.34
    long_only: bool = True
    name: str = "xs_momentum"

    def generate_signals(self, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        closes = panel_close(panel)
        mom = closes / closes.shift(self.lookback) - 1.0
        ranks = mom.rank(axis=1, method="first", ascending=False)
        n = closes.shape[1]
        k = max(1, int(round(n * self.top_fraction)))

        signals = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
        top = ranks <= k
        signals = signals.where(~top, other=1.0)
        if not self.long_only:
            bottom = ranks > (n - k)
            signals = signals.where(~bottom, other=-1.0)
        return signals.fillna(0.0)


@dataclass
class PerAssetStrategyAdapter(MultiAssetStrategy):
    """Run a single-asset Strategy independently on each symbol."""

    base: Strategy
    name: str = "per_asset_adapter"

    def generate_signals(self, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        cols = {}
        for sym, df in panel.items():
            cols[sym] = self.base.generate_signals(df)
        return pd.DataFrame(cols).fillna(0.0)
