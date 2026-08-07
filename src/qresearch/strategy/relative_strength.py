"""Relative-strength overlays for single-asset strategies."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from qresearch.strategy.base import Strategy


@dataclass
class RelativeStrengthEntryFilter(Strategy):
    """Filter entries by excess return vs a benchmark; exits follow the base.

    Rules (causal, bar-by-bar):
    - Flat → Long only if base wants long AND trailing excess >= threshold
    - Long → Flat when base wants flat/exit (e.g. MA cross / regime flat)
    - While long, RS falling below threshold does NOT force an exit
    """

    base: Strategy
    benchmark_close: pd.Series
    threshold: float = 0.05
    window: int = 20
    name: str = "rs_entry_filter"

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series | None:
        if hasattr(self.base, "generate_regimes"):
            return self.base.generate_regimes(data)
        return None

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        raw = self.base.generate_signals(data).astype(float).reindex(data.index)
        raw = raw.fillna(0.0)

        stock_ret = data["close"].astype(float).pct_change(self.window)
        bench = self.benchmark_close.astype(float).reindex(data.index).ffill()
        excess = stock_ret - bench.pct_change(self.window)
        can_enter = (excess >= self.threshold).fillna(False).to_numpy()
        base_long = (raw > 0).to_numpy()
        base_w = raw.to_numpy(dtype=float)

        out = np.zeros(len(data), dtype=float)
        pos = 0.0
        for i in range(len(data)):
            if pos == 0.0:
                if base_long[i] and can_enter[i]:
                    pos = base_w[i]
            else:
                # Exit only on base signal; RS does not flatten an open long.
                if not base_long[i]:
                    pos = 0.0
                else:
                    pos = base_w[i]
            out[i] = pos

        return pd.Series(out, index=data.index, name="signal")
