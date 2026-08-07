from __future__ import annotations

import numpy as np
import pandas as pd

from qresearch.strategy.beat_bench import SevereTrimFastReentryStrategy


def test_severe_trim_stays_mostly_long_in_uptrend():
    n = 300
    idx = pd.bdate_range("2023-01-01", periods=n)
    close = np.linspace(100, 200, n)
    data = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": 1e6,
        },
        index=idx,
    )
    sig = SevereTrimFastReentryStrategy().generate_signals(data)
    assert (sig >= 0).all() and (sig <= 1).all()
    assert sig.iloc[-60:].mean() > 0.9
