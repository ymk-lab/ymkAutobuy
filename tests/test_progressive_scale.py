from __future__ import annotations

import numpy as np
import pandas as pd

from qresearch.strategy.base import Strategy
from qresearch.strategy.progressive_scale import (
    MinCombineScale,
    PriceConfirmScale,
    TimeConfirmScale,
)


class AlwaysLong(Strategy):
    name = "always"

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=data.index)


def _ohlcv(n: int = 30) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=n)
    close = pd.Series(np.linspace(100, 110, n), index=idx)
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1e6},
        index=idx,
    )


def test_time_confirm_ramps():
    data = _ohlcv(20)
    sig = TimeConfirmScale(AlwaysLong(), days_to_w2=3, days_to_full=8).generate_signals(data)
    assert sig.iloc[0] == 0.25
    assert sig.iloc[2] == 0.50
    assert sig.iloc[7] == 1.0


def test_price_confirm_and_min_combine():
    idx = pd.bdate_range("2024-01-01", periods=10)
    close = pd.Series([100, 100.5, 101, 102.5, 103, 104, 105, 106, 107, 108], index=idx, dtype=float)
    data = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1.0},
        index=idx,
    )
    a = TimeConfirmScale(AlwaysLong(), days_to_w2=2, days_to_full=4, w1=0.25, w2=0.5)
    b = PriceConfirmScale(AlwaysLong(), extend_pct=0.02, w1=0.25, w2=0.5)
    combo = MinCombineScale(a, b).generate_signals(data)
    # min of both — never above either leg
    assert (combo <= a.generate_signals(data) + 1e-12).all()
    assert (combo <= b.generate_signals(data) + 1e-12).all()
