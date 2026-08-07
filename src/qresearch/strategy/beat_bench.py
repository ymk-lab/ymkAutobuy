"""Offensive beat-benchmark timing: default full long, cut only on severe risk."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from qresearch.regime.detector import VolatilityRegimeDetector
from qresearch.strategy.base import Strategy


@dataclass
class BeatBenchStrategy(Strategy):
    """Stay long by default; reduce/flat only on risk-off; re-enter fast.

    modes:
      - ma200: long iff close > MA200
      - ma200_fast_reentry: exit on MA200 break; re-enter on MA reentry_ma reclaim
      - severe: flat only if high-vol AND close < MA severe_ma; else full long
      - dual_confirm: flat if close < MA200 for confirm_days; re-enter on MA reentry_ma
      - hysteresis: exit MA200, enter MA enter_ma (enter_ma < 200), full or flat
    """

    mode: str = "hysteresis"
    ma_exit: int = 200
    ma_enter: int = 50
    severe_ma: int = 100
    reentry_ma: int = 50
    confirm_days: int = 2
    risk_off_weight: float = 0.0
    vol_lookback: int = 20
    vol_mult: float = 1.35
    name: str = "beat_bench"

    def __post_init__(self) -> None:
        mode = self.mode.lower()
        allowed = {"ma200", "ma200_fast_reentry", "severe", "dual_confirm", "hysteresis"}
        if mode not in allowed:
            raise ValueError(f"mode must be one of {sorted(allowed)}")
        self.mode = mode
        if not (0.0 <= self.risk_off_weight <= 1.0):
            raise ValueError("risk_off_weight must be in [0, 1]")
        self.detector = VolatilityRegimeDetector(
            lookback=self.vol_lookback, high_vol_multiplier=self.vol_mult
        )

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series:
        return self.detector.detect(data)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"].astype(float)
        ma_x = close.rolling(self.ma_exit, min_periods=self.ma_exit).mean()
        ma_e = close.rolling(self.ma_enter, min_periods=self.ma_enter).mean()
        ma_r = close.rolling(self.reentry_ma, min_periods=self.reentry_ma).mean()
        ma_s = close.rolling(self.severe_ma, min_periods=self.severe_ma).mean()
        regimes = self.generate_regimes(data)
        high_vol = (regimes == "high_vol").fillna(False)
        unknown = (regimes == "unknown").fillna(True)

        n = len(data)
        out = np.ones(n, dtype=float)  # default full long after warmup handled below
        c = close.to_numpy(dtype=float)
        x = ma_x.to_numpy(dtype=float)
        e = ma_e.to_numpy(dtype=float)
        r = ma_r.to_numpy(dtype=float)
        s = ma_s.to_numpy(dtype=float)
        hv = high_vol.to_numpy(dtype=bool)
        unk = unknown.to_numpy(dtype=bool)

        if self.mode == "ma200":
            for i in range(n):
                if unk[i] or not np.isfinite(x[i]):
                    out[i] = 0.0
                elif c[i] > x[i]:
                    out[i] = 1.0
                else:
                    out[i] = self.risk_off_weight
            return pd.Series(out, index=data.index, name="signal")

        if self.mode == "severe":
            for i in range(n):
                if unk[i] or not np.isfinite(s[i]):
                    out[i] = 0.0
                elif hv[i] and c[i] < s[i]:
                    out[i] = self.risk_off_weight
                else:
                    out[i] = 1.0
            return pd.Series(out, index=data.index, name="signal")

        # stateful modes
        in_pos = False
        below_streak = 0
        for i in range(n):
            if unk[i] or not np.isfinite(x[i]):
                in_pos = False
                below_streak = 0
                out[i] = 0.0
                continue

            if self.mode == "ma200_fast_reentry":
                if in_pos:
                    if c[i] < x[i]:
                        in_pos = False
                else:
                    if np.isfinite(r[i]) and c[i] > r[i]:
                        in_pos = True
            elif self.mode == "dual_confirm":
                if c[i] < x[i]:
                    below_streak += 1
                else:
                    below_streak = 0
                if in_pos:
                    if below_streak >= max(self.confirm_days, 1):
                        in_pos = False
                else:
                    if np.isfinite(r[i]) and c[i] > r[i]:
                        in_pos = True
            else:  # hysteresis
                if in_pos:
                    if c[i] < x[i]:
                        in_pos = False
                else:
                    if np.isfinite(e[i]) and c[i] > e[i]:
                        in_pos = True

            out[i] = 1.0 if in_pos else self.risk_off_weight

        return pd.Series(out, index=data.index, name="signal")


@dataclass
class SevereTrimFastReentryStrategy(Strategy):
    """Default full long; trim on severe risk; reclaim mid-MA to go full again.

    Risk-off (trim_weight):
      - high-vol AND close < severe_ma, OR
      - close < exit_ma for confirm_days consecutive bars
    Risk-on (1.0):
      - close > reentry_ma
    Otherwise keep prior state (hysteresis), starting full after warmup.
    """

    exit_ma: int = 200
    severe_ma: int = 100
    reentry_ma: int = 50
    confirm_days: int = 2
    trim_weight: float = 0.50
    vol_lookback: int = 20
    vol_mult: float = 1.35
    name: str = "severe_trim_fast_reentry"

    def __post_init__(self) -> None:
        if not (0.0 <= self.trim_weight <= 1.0):
            raise ValueError("trim_weight must be in [0, 1]")
        if self.confirm_days < 1:
            raise ValueError("confirm_days must be >= 1")
        if self.reentry_ma >= self.exit_ma:
            raise ValueError("reentry_ma should be faster than exit_ma")
        self.detector = VolatilityRegimeDetector(
            lookback=self.vol_lookback, high_vol_multiplier=self.vol_mult
        )

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series:
        return self.detector.detect(data)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"].astype(float)
        ma_x = close.rolling(self.exit_ma, min_periods=self.exit_ma).mean()
        ma_s = close.rolling(self.severe_ma, min_periods=self.severe_ma).mean()
        ma_r = close.rolling(self.reentry_ma, min_periods=self.reentry_ma).mean()
        regimes = self.generate_regimes(data)
        high_vol = (regimes == "high_vol").fillna(False)
        unknown = (regimes == "unknown").fillna(True)

        n = len(data)
        out = np.ones(n, dtype=float)
        c = close.to_numpy(dtype=float)
        x = ma_x.to_numpy(dtype=float)
        s = ma_s.to_numpy(dtype=float)
        r = ma_r.to_numpy(dtype=float)
        hv = high_vol.to_numpy(dtype=bool)
        unk = unknown.to_numpy(dtype=bool)

        weight = 1.0
        below_streak = 0
        for i in range(n):
            if unk[i] or not np.isfinite(x[i]) or not np.isfinite(s[i]):
                weight = 0.0
                below_streak = 0
                out[i] = 0.0
                continue

            if c[i] < x[i]:
                below_streak += 1
            else:
                below_streak = 0

            severe = (hv[i] and c[i] < s[i]) or (below_streak >= self.confirm_days)
            reclaim = np.isfinite(r[i]) and c[i] > r[i]

            if severe:
                weight = self.trim_weight
            elif reclaim:
                weight = 1.0
            # else keep prior weight
            out[i] = weight

        return pd.Series(out, index=data.index, name="signal")


@dataclass
class OffenseTrimStrategy(Strategy):
    """Stay mostly full; trim to trim_weight on medium risk; flat on severe.

    - full: close > MA200
    - trim: MA severe < close <= MA200 OR high-vol while above severe MA
    - flat: close <= MA severe
    """

    ma_trend: int = 200
    ma_severe: int = 100
    trim_weight: float = 0.70
    use_vol_trim: bool = True
    vol_lookback: int = 20
    vol_mult: float = 1.35
    name: str = "offense_trim"

    def __post_init__(self) -> None:
        if not (0.0 <= self.trim_weight <= 1.0):
            raise ValueError("trim_weight must be in [0, 1]")
        self.detector = VolatilityRegimeDetector(
            lookback=self.vol_lookback, high_vol_multiplier=self.vol_mult
        )

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series:
        return self.detector.detect(data)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"].astype(float)
        ma_t = close.rolling(self.ma_trend, min_periods=self.ma_trend).mean()
        ma_s = close.rolling(self.ma_severe, min_periods=self.ma_severe).mean()
        regimes = self.generate_regimes(data)
        high_vol = regimes == "high_vol"
        unknown = regimes == "unknown"

        full = (close > ma_t) & ~unknown
        flat = (close <= ma_s) | unknown
        trim = (~full) & (~flat)
        if self.use_vol_trim:
            trim = trim | ((high_vol) & (close > ma_s) & ~unknown)

        w = pd.Series(self.trim_weight, index=data.index, dtype=float)
        w = w.mask(full, other=1.0)
        w = w.mask(flat, other=0.0)
        # if both high-vol trim and full, prefer trim only when not full — already handled
        return w.fillna(0.0).clip(0.0, 1.0).rename("signal")
