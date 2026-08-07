from __future__ import annotations

import numpy as np
import pandas as pd

from qresearch.strategy.beat_bench import BeatBenchStrategy, OffenseTrimStrategy


def _data(n: int = 260) -> pd.DataFrame:
    idx = pd.bdate_range("2023-01-01", periods=n)
    close = np.linspace(100, 180, n) + np.sin(np.linspace(0, 12, n)) * 3
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1e6,
        },
        index=idx,
    )


def test_beat_bench_modes_bounded():
    data = _data()
    for mode in ("ma200", "ma200_fast_reentry", "severe", "dual_confirm", "hysteresis"):
        sig = BeatBenchStrategy(mode=mode).generate_signals(data)
        assert (sig >= 0).all() and (sig <= 1).all()
        assert sig.iloc[-50:].mean() > 0.5  # uptrend should stay mostly long


def test_offense_trim_prefers_full_in_uptrend():
    sig = OffenseTrimStrategy().generate_signals(_data())
    assert sig.iloc[-30:].mean() > 0.85
