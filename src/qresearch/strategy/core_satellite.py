"""Core-satellite book with soft volatility overlay on the core."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from qresearch.regime.detector import VolatilityRegimeDetector
from qresearch.strategy.base import Strategy
from qresearch.strategy.examples import RegimeAwareTrendStrategy


@dataclass
class CoreSatelliteSoftVolStrategy(Strategy):
    """70/30-style book: soft-vol core + binary satellite (e.g. S12).

    total_weight = core_weight * scale + satellite_weight * satellite_signal
    scale = clip(vol_target / realized_vol, core_scale_floor, 1.0)
    """

    core_weight: float = 0.70
    satellite_weight: float = 0.30
    vol_lookback: int = 20
    vol_target: float = 0.15
    core_scale_floor: float = 0.50
    # "D" = update soft-vol scale daily; "W" = freeze scale within calendar week
    soft_vol_cadence: str = "D"
    satellite: Strategy | None = None
    name: str = "core_satellite_soft_vol"

    def __post_init__(self) -> None:
        if self.satellite is None:
            self.satellite = RegimeAwareTrendStrategy(
                fast=10,
                slow=40,
                high_vol_weight=0.0,
                detector=VolatilityRegimeDetector(lookback=20, high_vol_multiplier=1.35),
            )
        if not (0.0 < self.core_weight <= 1.0):
            raise ValueError("core_weight must be in (0, 1]")
        if not (0.0 <= self.satellite_weight <= 1.0):
            raise ValueError("satellite_weight must be in [0, 1]")
        if self.core_weight + self.satellite_weight > 1.0 + 1e-12:
            raise ValueError("core_weight + satellite_weight must be <= 1")
        if not (0.0 < self.core_scale_floor <= 1.0):
            raise ValueError("core_scale_floor must be in (0, 1]")
        cadence = self.soft_vol_cadence.upper()
        if cadence not in {"D", "W"}:
            raise ValueError("soft_vol_cadence must be 'D' or 'W'")
        self.soft_vol_cadence = cadence

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series | None:
        assert self.satellite is not None
        if hasattr(self.satellite, "generate_regimes"):
            return self.satellite.generate_regimes(data)
        return None

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        assert self.satellite is not None
        close = data["close"].astype(float)
        ret = close.pct_change()
        realized = ret.rolling(self.vol_lookback, min_periods=self.vol_lookback).std() * np.sqrt(
            252.0
        )
        scale = (self.vol_target / realized).replace([np.inf, -np.inf], np.nan)
        scale = scale.clip(lower=self.core_scale_floor, upper=1.0).fillna(self.core_scale_floor)
        # Warmup: keep core at floor until vol is defined? Prefer full core target after floor fill.
        # Until lookback ready, use scale=1.0 (no overlay) only if we have prices; else 0.
        warm = realized.isna()
        scale = scale.mask(warm, other=1.0)
        if self.soft_vol_cadence == "W":
            # Update on week markers, hold through the week (causal: use week's first bar scale).
            week = scale.index.to_period("W-FRI")
            scale = scale.groupby(week).transform("first")

        sat = (
            self.satellite.generate_signals(data)
            .astype(float)
            .reindex(data.index)
            .fillna(0.0)
            .clip(lower=0.0, upper=1.0)
        )
        core = self.core_weight * scale
        total = (core + self.satellite_weight * sat).clip(upper=1.0)
        return total.rename("signal")


@dataclass
class BinaryEntryConfirm(Strategy):
    """Require base long for ``confirm_days`` before going long; exit with base."""

    base: Strategy
    confirm_days: int = 2
    name: str = "binary_entry_confirm"

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series | None:
        if hasattr(self.base, "generate_regimes"):
            return self.base.generate_regimes(data)
        return None

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        if self.confirm_days < 1:
            raise ValueError("confirm_days must be >= 1")
        raw = self.base.generate_signals(data).astype(float).reindex(data.index).fillna(0.0)
        base_long = (raw > 0).to_numpy()
        base_w = raw.to_numpy(dtype=float)
        out = np.zeros(len(data), dtype=float)
        streak = 0
        for i in range(len(data)):
            if not base_long[i]:
                streak = 0
                out[i] = 0.0
                continue
            streak += 1
            out[i] = base_w[i] if streak >= self.confirm_days else 0.0
        return pd.Series(out, index=data.index, name="signal")
