"""Simple market-regime detectors for research hooks."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class VolatilityRegimeDetector:
    """Classify bars into low/high volatility regimes.

    Uses rolling realized volatility vs a baseline median.
    Labels: "low_vol" | "high_vol" | "unknown"
    """

    lookback: int = 20
    high_vol_multiplier: float = 1.25
    # "expanding" = all history; "rolling" = trailing baseline_window bars
    baseline_mode: str = "expanding"
    baseline_window: int = 504  # ~2y trading days

    def __post_init__(self) -> None:
        mode = self.baseline_mode.lower()
        if mode not in {"expanding", "rolling"}:
            raise ValueError("baseline_mode must be 'expanding' or 'rolling'")
        self.baseline_mode = mode
        if self.baseline_window < self.lookback:
            raise ValueError("baseline_window must be >= lookback")

    def detect(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"].astype(float)
        ret = close.pct_change()
        vol = ret.rolling(self.lookback, min_periods=self.lookback).std()
        if self.baseline_mode == "expanding":
            baseline = vol.expanding(min_periods=self.lookback).median()
        else:
            baseline = vol.rolling(self.baseline_window, min_periods=self.lookback).median()
        high = vol > (baseline * self.high_vol_multiplier)
        labels = high.map({True: "high_vol", False: "low_vol"})
        labels = labels.where(vol.notna() & baseline.notna(), other="unknown")
        return labels.rename("regime")
