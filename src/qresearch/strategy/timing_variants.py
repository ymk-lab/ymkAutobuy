"""Timing variants for earlier exit / earlier entry experiments."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from qresearch.regime.detector import VolatilityRegimeDetector
from qresearch.strategy.base import Strategy


def _atr(data: pd.DataFrame, window: int = 14) -> pd.Series:
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    close = data["close"].astype(float)
    prev = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev).abs(), (low - prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window, min_periods=window).mean()


@dataclass
class TimingVariantStrategy(Strategy):
    """Stateful long/flat timing with selectable entry/exit rules.

    entry_mode:
      - cross: MA fast > MA slow (classic S12 entry leg)
      - pullback: slow MA rising and close reclaims MA pullback after a dip
      - fast: MA entry_fast > MA entry_slow
    exit_mode:
      - cross: MA fast < MA slow
      - ma_break: close < exit MA
      - atr: trailing ATR stop from entry / peak
      - hybrid: ma_break OR atr (whichever first)
    Always flats on high-vol / unknown when use_vol_filter=True.
    """

    entry_mode: str = "cross"
    exit_mode: str = "cross"
    fast: int = 10
    slow: int = 40
    entry_fast: int = 5
    entry_slow: int = 20
    exit_ma: int = 20
    pullback_ma: int = 20
    atr_window: int = 14
    atr_mult: float = 2.5
    high_vol_weight: float = 0.0
    use_vol_filter: bool = True
    vol_mult: float = 1.35
    vol_lookback: int = 20
    name: str = "timing_variant"

    def __post_init__(self) -> None:
        self.detector = VolatilityRegimeDetector(
            lookback=self.vol_lookback, high_vol_multiplier=self.vol_mult
        )
        em = self.entry_mode.lower()
        xm = self.exit_mode.lower()
        if em not in {"cross", "pullback", "fast"}:
            raise ValueError("entry_mode must be cross|pullback|fast")
        if xm not in {"cross", "ma_break", "atr", "hybrid"}:
            raise ValueError("exit_mode must be cross|ma_break|atr|hybrid")
        self.entry_mode = em
        self.exit_mode = xm

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series:
        return self.detector.detect(data)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"].astype(float)
        fast_ma = close.rolling(self.fast, min_periods=self.fast).mean()
        slow_ma = close.rolling(self.slow, min_periods=self.slow).mean()
        e_fast = close.rolling(self.entry_fast, min_periods=self.entry_fast).mean()
        e_slow = close.rolling(self.entry_slow, min_periods=self.entry_slow).mean()
        x_ma = close.rolling(self.exit_ma, min_periods=self.exit_ma).mean()
        pb_ma = close.rolling(self.pullback_ma, min_periods=self.pullback_ma).mean()
        atr = _atr(data, self.atr_window)
        regimes = self.generate_regimes(data)

        slow_rising = slow_ma.diff() > 0
        # dip then reclaim: yesterday at/below pullback MA, today above
        reclaim = (close.shift(1) <= pb_ma.shift(1)) & (close > pb_ma)
        entry_pullback = slow_rising & reclaim
        entry_cross = fast_ma > slow_ma
        entry_fast = e_fast > e_slow

        if self.entry_mode == "cross":
            want_enter = entry_cross
        elif self.entry_mode == "pullback":
            want_enter = entry_pullback
        else:
            want_enter = entry_fast

        exit_cross = fast_ma < slow_ma
        exit_ma_break = close < x_ma

        n = len(data)
        out = np.zeros(n, dtype=float)
        in_pos = False
        peak = 0.0
        stop = 0.0
        c = close.to_numpy(dtype=float)
        a = atr.to_numpy(dtype=float)
        vol_ok = ~regimes.isin(["high_vol", "unknown"]).to_numpy()
        if not self.use_vol_filter:
            vol_ok = np.ones(n, dtype=bool)

        we = want_enter.fillna(False).to_numpy()
        xc = exit_cross.fillna(False).to_numpy()
        xm = exit_ma_break.fillna(False).to_numpy()

        for i in range(n):
            if not in_pos:
                if we[i] and vol_ok[i] and np.isfinite(c[i]):
                    in_pos = True
                    peak = c[i]
                    if np.isfinite(a[i]):
                        stop = peak - self.atr_mult * a[i]
                    else:
                        stop = -np.inf
                    out[i] = 1.0
                else:
                    out[i] = 0.0
                continue

            # in position
            if np.isfinite(c[i]) and c[i] > peak:
                peak = c[i]
            if np.isfinite(a[i]):
                stop = max(stop, peak - self.atr_mult * a[i])

            atr_hit = np.isfinite(stop) and c[i] < stop
            if self.exit_mode == "cross":
                should_exit = bool(xc[i])
            elif self.exit_mode == "ma_break":
                should_exit = bool(xm[i])
            elif self.exit_mode == "atr":
                should_exit = bool(atr_hit)
            else:  # hybrid
                should_exit = bool(xm[i] or atr_hit)

            if (not vol_ok[i]) or should_exit:
                in_pos = False
                peak = 0.0
                stop = 0.0
                out[i] = float(self.high_vol_weight)
            else:
                out[i] = 1.0

        return pd.Series(out, index=data.index, name="signal")
