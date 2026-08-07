from __future__ import annotations

import numpy as np
import pandas as pd

from qresearch.strategy.timing_variants import TimingVariantStrategy


def _ohlcv(n: int = 120, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.001, 0.015, size=n)
    close = 100 * np.cumprod(1 + rets)
    idx = pd.bdate_range("2024-01-01", periods=n)
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


def test_timing_variants_long_only_binary():
    data = _ohlcv()
    for entry in ("cross", "pullback", "fast"):
        for exit_mode in ("cross", "ma_break", "atr", "hybrid"):
            s = TimingVariantStrategy(entry_mode=entry, exit_mode=exit_mode)
            sig = s.generate_signals(data)
            assert (sig >= 0).all()
            assert (sig <= 1).all()
            assert sig.notna().all()
