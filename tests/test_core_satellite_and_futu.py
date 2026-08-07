from __future__ import annotations

import numpy as np
import pandas as pd

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.strategy.base import Strategy
from qresearch.strategy.core_satellite import CoreSatelliteSoftVolStrategy


class AlwaysHalf(Strategy):
    name = "half"

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=data.index)


def test_futu_min_fees_dominate_tiny_trade():
    fees = FutuUsEquityFees(slippage_bps=3.0)
    # ~1 share at $500
    cost = fees.total_cost_usd(500.0, 500.0)
    assert cost > 1.99  # mins + clearance + slip


def test_core_floor_and_satellite_add():
    idx = pd.bdate_range("2024-01-01", periods=80)
    # High vol path so soft-vol should hit floor
    rng = np.random.default_rng(0)
    rets = rng.normal(0, 0.03, size=len(idx))  # very high daily vol
    close = 100 * np.cumprod(1 + rets)
    data = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1e6,
        },
        index=idx,
    )
    strat = CoreSatelliteSoftVolStrategy(
        core_weight=0.7,
        satellite_weight=0.3,
        vol_target=0.15,
        core_scale_floor=0.5,
        satellite=AlwaysHalf(),
    )
    sig = strat.generate_signals(data).iloc[40:]
    # core at floor 0.35 + satellite 0.3 = 0.65
    assert (sig >= 0.35 - 1e-9).all()
    assert (sig <= 1.0 + 1e-9).all()
    assert sig.max() >= 0.6
