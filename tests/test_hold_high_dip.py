from __future__ import annotations

import numpy as np
import pandas as pd

from qresearch.strategy.hold_high_dip import HoldHighDipScaleStrategy


def test_hold_high_dip_requires_benchmark():
    idx = pd.bdate_range("2024-01-01", periods=80)
    close = np.linspace(100, 120, 80)
    data = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1e6},
        index=idx,
    )
    s = HoldHighDipScaleStrategy()
    try:
        s.generate_signals(data)
        assert False, "expected ValueError"
    except ValueError:
        pass
    s.set_benchmark(pd.Series(close * 1.01, index=idx))
    sig = s.generate_signals(data)
    assert (sig >= 0).all() and (sig <= 1).all()
    assert sig.iloc[-10:].mean() > 0.9
