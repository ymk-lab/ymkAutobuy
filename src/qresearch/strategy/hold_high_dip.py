"""Hold through highs; sell on confirmed reverse; scale in on relative underperformance."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from qresearch.strategy.base import Strategy


@dataclass
class HoldHighDipScaleStrategy(Strategy):
    """Offense book with relative-dip scaling.

    Logic (a priori):
    1. **高位保留** — while above the trend MA, stay fully long (do not trim
       because price is extended).
    2. **訊號反轉到某程度才賣** — only after close stays below ``exit_ma`` for
       ``exit_confirm`` consecutive days, go flat.
    3. **跌超大盤逐步建倉** — while not fully long, if the asset's
       ``rel_lookback`` return lags the benchmark by more than ``rel_lag``,
       add ``add_step`` each day, capped at ``max_dip_weight`` (最多加一半).
    4. **訊號反轉回多 → 全倉** — when close reclaims ``reclaim_ma``
       (default = exit_ma), jump to 100%.

    Requires benchmark close via ``set_benchmark`` or ``data['benchmark_close']``.
    """

    exit_ma: int = 50
    reclaim_ma: int | None = None  # default: same as exit_ma
    exit_confirm: int = 2
    rel_lookback: int = 20
    rel_lag: float = 0.03
    add_step: float = 0.10
    max_dip_weight: float = 0.50
    name: str = "hold_high_dip_scale"

    def __post_init__(self) -> None:
        if self.reclaim_ma is None:
            self.reclaim_ma = self.exit_ma
        if not (0.0 < self.max_dip_weight <= 1.0):
            raise ValueError("max_dip_weight must be in (0, 1]")
        if not (0.0 < self.add_step <= self.max_dip_weight + 1e-12):
            raise ValueError("add_step must be in (0, max_dip_weight]")
        if self.exit_confirm < 1:
            raise ValueError("exit_confirm must be >= 1")
        self._benchmark_close: pd.Series | None = None

    def set_benchmark(self, close: pd.Series) -> None:
        self._benchmark_close = close.astype(float)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"].astype(float)
        if "benchmark_close" in data.columns:
            bench = data["benchmark_close"].astype(float).reindex(data.index)
        elif self._benchmark_close is not None:
            bench = self._benchmark_close.reindex(data.index)
        else:
            raise ValueError("benchmark close required (set_benchmark or data['benchmark_close'])")

        assert self.reclaim_ma is not None
        mx = close.rolling(self.exit_ma, min_periods=self.exit_ma).mean()
        mr = close.rolling(self.reclaim_ma, min_periods=self.reclaim_ma).mean()
        asset_ret = close / close.shift(self.rel_lookback) - 1.0
        bench_ret = bench / bench.shift(self.rel_lookback) - 1.0
        lag = asset_ret - bench_ret  # negative ⇒ 跌超大盤

        n = len(data)
        out = np.zeros(n, dtype=float)
        weight = 0.0
        below_streak = 0
        c = close.to_numpy(dtype=float)
        x = mx.to_numpy(dtype=float)
        rc = mr.to_numpy(dtype=float)
        lag_a = lag.to_numpy(dtype=float)

        for i in range(n):
            if not np.isfinite(x[i]) or not np.isfinite(rc[i]):
                weight = 0.0
                below_streak = 0
                out[i] = 0.0
                continue

            if c[i] < x[i]:
                below_streak += 1
            else:
                below_streak = 0

            full = weight >= 1.0 - 1e-12

            # 4) reclaim trend MA → full again
            if c[i] > rc[i]:
                weight = 1.0
            # 2) only sell from a full book after confirmed reverse
            elif full and below_streak >= self.exit_confirm:
                weight = 0.0
            # 3) after exit (or never full): 跌超大盤 → scale in up to half
            elif (not full) and np.isfinite(lag_a[i]) and lag_a[i] < -abs(self.rel_lag):
                weight = min(self.max_dip_weight, weight + self.add_step)
            # else keep (高位保留 while full & reverse not confirmed)
            out[i] = weight

        return pd.Series(out, index=data.index, name="signal")
