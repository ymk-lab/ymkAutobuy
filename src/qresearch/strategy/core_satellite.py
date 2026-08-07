"""Core-satellite book with soft volatility overlay on the core."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from qresearch.regime.detector import VolatilityRegimeDetector
from qresearch.strategy.base import Strategy
from qresearch.strategy.examples import RegimeAwareTrendStrategy


@dataclass
class CoreSatelliteSoftVolStrategy(Strategy):
    """Core soft-vol book + satellite signal (e.g. S12).

    total_weight = core_weight * scale + satellite_weight * satellite_signal
    scale = clip(vol_target / realized_vol, core_scale_floor, 1.0)
    """

    core_weight: float = 0.70
    satellite_weight: float = 0.30
    vol_lookback: int = 20
    vol_target: float = 0.15
    core_scale_floor: float = 0.50
    soft_vol_cadence: str = "W"  # W weekly (default), D daily
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
        self.last_event_mask: pd.Series | None = None

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
        warm = realized.isna()
        scale = scale.mask(warm, other=1.0)

        week = pd.Series(scale.index.to_period("W-FRI"), index=scale.index)
        week_start = (week != week.shift(1)).fillna(True)
        if self.soft_vol_cadence == "W":
            scale = scale.groupby(week).transform("first")

        sat = (
            self.satellite.generate_signals(data)
            .astype(float)
            .reindex(data.index)
            .fillna(0.0)
            .clip(lower=0.0, upper=1.0)
        )
        sat_on = sat > 0
        sat_event = sat_on != sat_on.shift(1).fillna(False)

        core = self.core_weight * scale
        total = (core + self.satellite_weight * sat).clip(upper=1.0)

        # Events: week boundary (core retune) or satellite flip.
        self.last_event_mask = (week_start | sat_event).reindex(data.index).fillna(True)
        return total.rename("signal")


@dataclass
class RegimeCoreSatelliteStrategy(Strategy):
    """Regime-aware core-satellite: switch book mix; core can exit on trend break.

    - bull (close > MA200 and not high-vol): higher core / lower satellite
    - base (close > soft MA, else not bull): classic core/sat mix
    - bear (close <= soft MA): core can go to bear_core (default 0); satellite keeps timing

    Soft-vol still scales the *active* core target weekly; when core target is 0,
    soft-vol does not reintroduce exposure.
    """

    bull_core: float = 0.85
    bull_sat: float = 0.15
    base_core: float = 0.70
    base_sat: float = 0.30
    bear_core: float = 0.0
    bear_sat: float = 0.30
    ma_trend: int = 200
    ma_soft: int = 100
    vol_lookback: int = 20
    vol_target: float = 0.15
    core_scale_floor: float = 0.50
    soft_vol_cadence: str = "W"
    vol_mult: float = 1.35
    satellite: Strategy | None = None
    name: str = "regime_core_satellite"

    def __post_init__(self) -> None:
        if self.satellite is None:
            self.satellite = RegimeAwareTrendStrategy(
                fast=10,
                slow=40,
                high_vol_weight=0.0,
                detector=VolatilityRegimeDetector(
                    lookback=20, high_vol_multiplier=self.vol_mult
                ),
            )
        for label, core, sat in (
            ("bull", self.bull_core, self.bull_sat),
            ("base", self.base_core, self.base_sat),
            ("bear", self.bear_core, self.bear_sat),
        ):
            if core < 0 or sat < 0 or core + sat > 1.0 + 1e-12:
                raise ValueError(f"{label} core/sat invalid")
        if self.ma_soft < 2 or self.ma_trend < self.ma_soft:
            raise ValueError("require 2 <= ma_soft <= ma_trend")
        if not (0.0 <= self.core_scale_floor <= 1.0):
            raise ValueError("core_scale_floor must be in [0, 1]")
        cadence = self.soft_vol_cadence.upper()
        if cadence not in {"D", "W"}:
            raise ValueError("soft_vol_cadence must be 'D' or 'W'")
        self.soft_vol_cadence = cadence
        self.vol_detector = VolatilityRegimeDetector(
            lookback=self.vol_lookback, high_vol_multiplier=self.vol_mult
        )
        self.last_event_mask: pd.Series | None = None
        self.last_book_regime: pd.Series | None = None

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series | None:
        assert self.satellite is not None
        if hasattr(self.satellite, "generate_regimes"):
            return self.satellite.generate_regimes(data)
        return None

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        assert self.satellite is not None
        close = data["close"].astype(float)
        ma_t = close.rolling(self.ma_trend, min_periods=self.ma_trend).mean()
        ma_s = close.rolling(self.ma_soft, min_periods=self.ma_soft).mean()
        vol_reg = self.vol_detector.detect(data)
        high_vol = vol_reg == "high_vol"
        unknown = vol_reg == "unknown"

        above_trend = (close > ma_t).fillna(False)
        above_soft = (close > ma_s).fillna(False)
        bull = above_trend & ~high_vol & ~unknown
        bear = (~above_soft) | unknown
        # base = neither bull nor bear (incl. above soft but not bull, or high-vol while above soft)
        book = pd.Series("base", index=data.index, dtype=object)
        book = book.mask(bull, other="bull")
        book = book.mask(bear, other="bear")
        # high-vol while still above soft MA: defensive base (keep core but soft-vol will cut)
        book = book.mask(high_vol & above_soft & ~bear, other="base")
        self.last_book_regime = book.rename("book_regime")

        core_tgt = pd.Series(self.base_core, index=data.index, dtype=float)
        sat_tgt = pd.Series(self.base_sat, index=data.index, dtype=float)
        core_tgt = core_tgt.mask(book == "bull", other=self.bull_core)
        sat_tgt = sat_tgt.mask(book == "bull", other=self.bull_sat)
        core_tgt = core_tgt.mask(book == "bear", other=self.bear_core)
        sat_tgt = sat_tgt.mask(book == "bear", other=self.bear_sat)

        ret = close.pct_change()
        realized = ret.rolling(self.vol_lookback, min_periods=self.vol_lookback).std() * np.sqrt(
            252.0
        )
        scale = (self.vol_target / realized).replace([np.inf, -np.inf], np.nan)
        scale = scale.clip(lower=self.core_scale_floor, upper=1.0).fillna(self.core_scale_floor)
        scale = scale.mask(realized.isna(), other=1.0)

        week = pd.Series(scale.index.to_period("W-FRI"), index=scale.index)
        week_start = (week != week.shift(1)).fillna(True)
        if self.soft_vol_cadence == "W":
            scale = scale.groupby(week).transform("first")

        # No soft-vol resurrection when core target is flat.
        core = (core_tgt * scale).where(core_tgt > 0, other=0.0)

        sat = (
            self.satellite.generate_signals(data)
            .astype(float)
            .reindex(data.index)
            .fillna(0.0)
            .clip(lower=0.0, upper=1.0)
        )
        sat_on = sat > 0
        sat_event = sat_on != sat_on.shift(1).fillna(False)
        book_event = book != book.shift(1)

        total = (core + sat_tgt * sat).clip(lower=0.0, upper=1.0)
        self.last_event_mask = (week_start | sat_event | book_event).reindex(data.index).fillna(True)
        return total.rename("signal")


@dataclass
class BinaryEntryConfirm(Strategy):
    """Asymmetric confirmation for entries/exits on a binary-ish base signal.

    ``entry_confirm_days=0`` / ``exit_confirm_days=0`` means act on the first
    confirming bar (immediate).
    """

    base: Strategy
    entry_confirm_days: int = 2
    exit_confirm_days: int = 0
    name: str = "binary_entry_confirm"

    def __post_init__(self) -> None:
        if self.entry_confirm_days < 0 or self.exit_confirm_days < 0:
            raise ValueError("confirm days must be >= 0")

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series | None:
        if hasattr(self.base, "generate_regimes"):
            return self.base.generate_regimes(data)
        return None

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        raw = self.base.generate_signals(data).astype(float).reindex(data.index).fillna(0.0)
        base_long = (raw > 0).to_numpy()
        base_w = raw.to_numpy(dtype=float)
        out = np.zeros(len(data), dtype=float)
        pos = 0.0
        last_long_w = 1.0
        up_streak = 0
        down_streak = 0
        entry_need = 1 if self.entry_confirm_days == 0 else self.entry_confirm_days
        exit_need = 1 if self.exit_confirm_days == 0 else self.exit_confirm_days

        for i in range(len(data)):
            if base_long[i]:
                up_streak += 1
                down_streak = 0
                last_long_w = base_w[i]
            else:
                down_streak += 1
                up_streak = 0

            if pos == 0.0:
                if base_long[i] and up_streak >= entry_need:
                    pos = base_w[i]
            elif base_long[i]:
                pos = base_w[i]
            elif down_streak >= exit_need:
                pos = 0.0
            else:
                # waiting for exit confirmation; keep last long weight
                pos = last_long_w
            out[i] = pos
        return pd.Series(out, index=data.index, name="signal")


@dataclass
class LongMAGate(Strategy):
    """Allow base longs only when close is above a long moving average."""

    base: Strategy
    ma_window: int = 200
    name: str = "long_ma_gate"

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series | None:
        if hasattr(self.base, "generate_regimes"):
            return self.base.generate_regimes(data)
        return None

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        if self.ma_window < 2:
            raise ValueError("ma_window must be >= 2")
        raw = self.base.generate_signals(data).astype(float).reindex(data.index).fillna(0.0)
        close = data["close"].astype(float)
        ma = close.rolling(self.ma_window, min_periods=self.ma_window).mean()
        ok = (close > ma).fillna(False)
        out = raw.where(ok, other=0.0)
        return out.rename("signal")
