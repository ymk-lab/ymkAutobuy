"""Simple market-regime detectors for research hooks."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class VolatilityRegimeDetector:
    """Classify bars into low/high volatility regimes.

    Uses rolling realized volatility vs a long-run median.
    Labels: "low_vol" | "high_vol"
    """

    lookback: int = 20
    high_vol_multiplier: float = 1.25

    def detect(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"].astype(float)
        ret = close.pct_change()
        vol = ret.rolling(self.lookback, min_periods=self.lookback).std()
        baseline = vol.expanding(min_periods=self.lookback).median()
        high = vol > (baseline * self.high_vol_multiplier)
        labels = high.map({True: "high_vol", False: "low_vol"})
        # Warmup period: mark unknown so strategies can stay flat.
        labels = labels.where(vol.notna(), other="unknown")
        return labels.rename("regime")
