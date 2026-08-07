"""Dip-probe overlay: partial entry on large pullbacks, full on base signal."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from qresearch.strategy.base import Strategy


@dataclass
class DipProbeEntryFilter(Strategy):
    """S12-style base plus a fractional dip probe before full confirmation.

    Position states (long-only weights):
    - FLAT (0): no position
    - DIP (dip_weight): entered because rolling drawdown from a recent high
      reached ``dip_threshold``
    - FULL (base weight, typically 1.0): entered/upgraded when ``base`` wants
      long (e.g. regime交叉 + RS entry filter)

    Transitions (causal, bar-by-bar):
    - FLAT → FULL if base long
    - FLAT → DIP if not base long and drawdown >= dip_threshold
    - DIP → FULL if base long
    - DIP → FLAT if close falls ``dip_stop`` from the dip entry price
    - FULL → FLAT when base is not long (exits follow the base / RS rules)

    After a dip stop, a new DIP entry is blocked until drawdown heals above
    ``-dip_threshold`` (must leave the dip zone first), avoiding immediate
    re-entry whipsaws while price is still deep in the hole.
    """

    base: Strategy
    dip_threshold: float = 0.10
    dip_weight: float = 0.25
    drawdown_lookback: int = 60
    dip_stop: float = 0.12
    name: str = "dip_probe_entry"

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series | None:
        if hasattr(self.base, "generate_regimes"):
            return self.base.generate_regimes(data)
        return None

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        if self.dip_threshold <= 0:
            raise ValueError("dip_threshold must be positive")
        if not (0.0 < self.dip_weight < 1.0):
            raise ValueError("dip_weight must be in (0, 1)")
        if self.drawdown_lookback < 2:
            raise ValueError("drawdown_lookback must be >= 2")
        if self.dip_stop <= 0:
            raise ValueError("dip_stop must be positive")

        raw = self.base.generate_signals(data).astype(float).reindex(data.index)
        raw = raw.fillna(0.0)
        close = data["close"].astype(float).reindex(data.index)
        roll_high = close.rolling(self.drawdown_lookback, min_periods=self.drawdown_lookback).max()
        dd = (close / roll_high - 1.0).to_numpy(dtype=float)
        base_long = (raw > 0).to_numpy()
        base_w = raw.to_numpy(dtype=float)
        px = close.to_numpy(dtype=float)

        out = np.zeros(len(data), dtype=float)
        # state: 0=flat, 1=dip, 2=full
        state = 0
        dip_entry_px = np.nan
        dip_reentry_blocked = False

        for i in range(len(data)):
            dd_i = dd[i]
            if dip_reentry_blocked and np.isfinite(dd_i) and dd_i > -self.dip_threshold:
                dip_reentry_blocked = False

            if state == 2:
                if not base_long[i]:
                    state = 0
                    dip_entry_px = np.nan
                    out[i] = 0.0
                else:
                    out[i] = base_w[i]
                continue

            if state == 1:
                # Stop the probe on further adverse move from dip entry.
                if np.isfinite(dip_entry_px) and px[i] <= dip_entry_px * (1.0 - self.dip_stop):
                    state = 0
                    dip_entry_px = np.nan
                    dip_reentry_blocked = True
                    out[i] = 0.0
                    continue
                if base_long[i]:
                    state = 2
                    dip_entry_px = np.nan
                    out[i] = base_w[i]
                else:
                    out[i] = self.dip_weight
                continue

            # flat
            if base_long[i]:
                state = 2
                dip_reentry_blocked = False
                out[i] = base_w[i]
            elif (
                (not dip_reentry_blocked)
                and np.isfinite(dd_i)
                and dd_i <= -self.dip_threshold
            ):
                state = 1
                dip_entry_px = px[i]
                out[i] = self.dip_weight
            else:
                out[i] = 0.0

        return pd.Series(out, index=data.index, name="signal")
