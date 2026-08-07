"""Example research strategies."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from qresearch.regime.detector import VolatilityRegimeDetector
from qresearch.strategy.base import Strategy


@dataclass
class SMACrossoverStrategy(Strategy):
    """Classic SMA crossover: long when fast > slow, else flat/short."""

    fast: int = 10
    slow: int = 30
    short_when_bearish: bool = False
    name: str = "sma_crossover"

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        if self.fast >= self.slow:
            raise ValueError("fast must be < slow")
        close = data["close"].astype(float)
        fast_ma = close.rolling(self.fast, min_periods=self.fast).mean()
        slow_ma = close.rolling(self.slow, min_periods=self.slow).mean()
        long_sig = (fast_ma > slow_ma).astype(float)
        if self.short_when_bearish:
            signal = long_sig.where(long_sig > 0, other=-1.0)
        else:
            signal = long_sig
        return signal.fillna(0.0).rename("signal")


@dataclass
class RegimeAwareTrendStrategy(Strategy):
    """regime交叉策略 (regime crossover).

    Rules:
    - Long when MA is bullish (fast > slow) AND regime is not high-vol
    - Flat when MA turns bearish OR regime enters high-vol (or unknown warmup)

    Chinese name: regime交叉策略
    """

    fast: int = 10
    slow: int = 40
    high_vol_weight: float = 0.0
    detector: VolatilityRegimeDetector | None = None
    name: str = "regime_crossover"

    def __post_init__(self) -> None:
        if self.detector is None:
            self.detector = VolatilityRegimeDetector()

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series:
        assert self.detector is not None
        return self.detector.detect(data)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"].astype(float)
        fast_ma = close.rolling(self.fast, min_periods=self.fast).mean()
        slow_ma = close.rolling(self.slow, min_periods=self.slow).mean()
        trend = (fast_ma > slow_ma).astype(float)
        regimes = self.generate_regimes(data)

        weight = trend.copy()
        weight = weight.where(regimes != "high_vol", other=self.high_vol_weight)
        weight = weight.where(regimes != "unknown", other=0.0)
        return weight.fillna(0.0).rename("signal")


# Alias kept for older imports / notebooks.
RegimeCrossoverStrategy = RegimeAwareTrendStrategy
