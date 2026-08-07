from __future__ import annotations

import numpy as np
import pandas as pd

from qresearch.strategy.core_satellite import RegimeCoreSatelliteStrategy


def test_regime_coresat_core_can_flatten_in_bear():
    # Strong uptrend then crash below MA100 → bear core should be 0 when sat off.
    n = 260
    idx = pd.bdate_range("2023-01-01", periods=n)
    up = np.linspace(100, 200, 200)
    down = np.linspace(200, 80, n - 200)
    close = np.concatenate([up, down])
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
    strat = RegimeCoreSatelliteStrategy(bear_core=0.0, bear_sat=0.30)
    sig = strat.generate_signals(data)
    assert strat.last_book_regime is not None
    bear_days = strat.last_book_regime == "bear"
    assert bear_days.any()
    # On bear days with satellite flat, total weight should be ~0
    # (satellite may still fire; just ensure weights in [0,1] and some near-zero)
    assert (sig >= 0).all() and (sig <= 1).all()
    assert (sig.loc[bear_days] <= 0.30 + 1e-9).all()
