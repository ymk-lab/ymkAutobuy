"""Progressive scale-in overlays to reduce false-signal full entries."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from qresearch.strategy.base import Strategy


def _base_long_weight(base: Strategy, data: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, pd.Series | None]:
    raw = base.generate_signals(data).astype(float).reindex(data.index).fillna(0.0)
    regimes = None
    if hasattr(base, "generate_regimes"):
        regimes = base.generate_regimes(data)
        if regimes is not None:
            regimes = regimes.reindex(data.index)
    return (raw > 0).to_numpy(), raw.to_numpy(dtype=float), regimes


@dataclass
class TimeConfirmScale(Strategy):
    """Scale in by how long the base signal stays on."""

    base: Strategy
    w1: float = 0.25
    w2: float = 0.50
    days_to_w2: int = 3
    days_to_full: int = 8
    name: str = "time_confirm_scale"

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series | None:
        if hasattr(self.base, "generate_regimes"):
            return self.base.generate_regimes(data)
        return None

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        base_long, base_w, _ = _base_long_weight(self.base, data)
        out = np.zeros(len(data), dtype=float)
        streak = 0
        for i in range(len(data)):
            if not base_long[i]:
                streak = 0
                out[i] = 0.0
                continue
            streak += 1
            if streak >= self.days_to_full:
                out[i] = base_w[i]
            elif streak >= self.days_to_w2:
                out[i] = self.w2 * base_w[i]
            else:
                out[i] = self.w1 * base_w[i]
        return pd.Series(out, index=data.index, name="signal")


@dataclass
class PriceConfirmScale(Strategy):
    """Scale in only if price holds above entry and then extends."""

    base: Strategy
    w1: float = 0.25
    w2: float = 0.50
    extend_pct: float = 0.02
    stop_pct: float = 0.04
    name: str = "price_confirm_scale"

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series | None:
        if hasattr(self.base, "generate_regimes"):
            return self.base.generate_regimes(data)
        return None

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        base_long, base_w, _ = _base_long_weight(self.base, data)
        px = data["close"].astype(float).to_numpy()
        out = np.zeros(len(data), dtype=float)
        entry = np.nan
        stopped = False

        for i in range(len(data)):
            if not base_long[i]:
                entry = np.nan
                stopped = False
                out[i] = 0.0
                continue

            if stopped:
                out[i] = 0.0
                continue

            if not np.isfinite(entry):
                entry = px[i]
                out[i] = self.w1 * base_w[i]
                continue

            if px[i] <= entry * (1.0 - self.stop_pct):
                stopped = True
                out[i] = 0.0
            elif px[i] >= entry * (1.0 + self.extend_pct):
                out[i] = base_w[i]
            elif px[i] >= entry:
                out[i] = self.w2 * base_w[i]
            else:
                out[i] = self.w1 * base_w[i]

        return pd.Series(out, index=data.index, name="signal")


@dataclass
class PullbackAddScale(Strategy):
    """Enter small on signal; add on controlled pullback while base still long."""

    base: Strategy
    w_signal: float = 0.25
    w_add: float = 0.50
    pullback_pct: float = 0.06
    add_stop_pct: float = 0.10
    name: str = "pullback_add_scale"

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series | None:
        if hasattr(self.base, "generate_regimes"):
            return self.base.generate_regimes(data)
        return None

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        base_long, base_w, _ = _base_long_weight(self.base, data)
        px = data["close"].astype(float).to_numpy()
        out = np.zeros(len(data), dtype=float)
        high_since = np.nan
        added = False
        add_px = np.nan

        for i in range(len(data)):
            if not base_long[i]:
                high_since = np.nan
                added = False
                add_px = np.nan
                out[i] = 0.0
                continue

            if not np.isfinite(high_since):
                high_since = px[i]
                out[i] = self.w_signal * base_w[i]
                continue

            high_since = max(high_since, px[i])
            dd = px[i] / high_since - 1.0

            if added:
                if np.isfinite(add_px) and px[i] <= add_px * (1.0 - self.add_stop_pct):
                    out[i] = 0.0
                    high_since = np.nan
                    added = False
                    add_px = np.nan
                    continue
                if px[i] >= high_since:
                    out[i] = base_w[i]
                else:
                    out[i] = self.w_add * base_w[i]
            elif dd <= -self.pullback_pct:
                added = True
                add_px = px[i]
                out[i] = self.w_add * base_w[i]
            else:
                out[i] = self.w_signal * base_w[i]

        return pd.Series(out, index=data.index, name="signal")


@dataclass
class RegimeTierScale(Strategy):
    """Time-based scale-in, but cap size when volatility regime is elevated."""

    base: Strategy
    w1: float = 0.25
    w2: float = 0.50
    days_to_w2: int = 2
    days_to_full: int = 5
    elevated_vol_mult: float = 1.20
    elevated_cap: float = 0.50
    vol_lookback: int = 20
    name: str = "regime_tier_scale"

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series | None:
        if hasattr(self.base, "generate_regimes"):
            return self.base.generate_regimes(data)
        return None

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        base_long, base_w, regimes = _base_long_weight(self.base, data)
        close = data["close"].astype(float)
        ret = close.pct_change()
        vol = ret.rolling(self.vol_lookback, min_periods=self.vol_lookback).std()
        baseline = vol.expanding(min_periods=self.vol_lookback).median()
        elevated = (vol > baseline * self.elevated_vol_mult).fillna(False).to_numpy()
        high_vol = np.zeros(len(data), dtype=bool)
        if regimes is not None:
            high_vol = (regimes == "high_vol").fillna(False).to_numpy()

        out = np.zeros(len(data), dtype=float)
        streak = 0
        for i in range(len(data)):
            if not base_long[i] or high_vol[i]:
                streak = 0
                out[i] = 0.0
                continue
            streak += 1
            if streak >= self.days_to_full:
                w = base_w[i]
            elif streak >= self.days_to_w2:
                w = self.w2 * base_w[i]
            else:
                w = self.w1 * base_w[i]
            if elevated[i]:
                w = min(w, self.elevated_cap * abs(base_w[i]))
            out[i] = w
        return pd.Series(out, index=data.index, name="signal")


@dataclass
class PyramidScale(Strategy):
    """Pyramid into winners: add only after floating profit thresholds."""

    base: Strategy
    w1: float = 0.20
    w2: float = 0.50
    profit_to_w2: float = 0.03
    profit_to_full: float = 0.06
    giveback_cut: float = 0.05
    name: str = "pyramid_scale"

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series | None:
        if hasattr(self.base, "generate_regimes"):
            return self.base.generate_regimes(data)
        return None

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        base_long, base_w, _ = _base_long_weight(self.base, data)
        px = data["close"].astype(float).to_numpy()
        out = np.zeros(len(data), dtype=float)
        entry = np.nan
        peak = np.nan
        level = 0  # 0 flat/partial tracking, 1=w1, 2=w2, 3=full

        for i in range(len(data)):
            if not base_long[i]:
                entry = np.nan
                peak = np.nan
                level = 0
                out[i] = 0.0
                continue

            if not np.isfinite(entry):
                entry = px[i]
                peak = px[i]
                level = 1
                out[i] = self.w1 * base_w[i]
                continue

            peak = max(peak, px[i])
            pnl = px[i] / entry - 1.0
            dd_from_peak = px[i] / peak - 1.0

            if dd_from_peak <= -self.giveback_cut and level >= 2:
                level = 1
                out[i] = self.w1 * base_w[i]
                continue

            if pnl >= self.profit_to_full:
                level = 3
                out[i] = base_w[i]
            elif pnl >= self.profit_to_w2:
                level = 2
                out[i] = self.w2 * base_w[i]
            else:
                level = 1
                out[i] = self.w1 * base_w[i]

        return pd.Series(out, index=data.index, name="signal")


@dataclass
class MinCombineScale(Strategy):
    """Pair two progressive overlays: position = min(w_a, w_b)."""

    a: Strategy
    b: Strategy
    name: str = "min_combine_scale"

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series | None:
        if hasattr(self.a, "generate_regimes"):
            return self.a.generate_regimes(data)
        if hasattr(self.b, "generate_regimes"):
            return self.b.generate_regimes(data)
        return None

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        wa = self.a.generate_signals(data).astype(float).reindex(data.index).fillna(0.0)
        wb = self.b.generate_signals(data).astype(float).reindex(data.index).fillna(0.0)
        # same sign assumed long-only; take min magnitude
        out = np.minimum(wa.to_numpy(), wb.to_numpy())
        return pd.Series(out, index=data.index, name="signal")
