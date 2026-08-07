"""Synthetic market data for offline research demos and tests."""

from __future__ import annotations

import numpy as np
import pandas as pd


def generate_synthetic_ohlcv(
    n: int = 750,
    *,
    start: str = "2022-01-01",
    seed: int = 7,
    annual_vol: float = 0.20,
    drift: float = 0.05,
    regime_breaks: tuple[int, ...] = (250, 500),
) -> pd.DataFrame:
    """Generate daily OHLCV with simple volatility regime shifts.

    Regime map (by default):
    - [0, 250): calm trend
    - [250, 500): high-vol chop
    - [500, n): resumed trend
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start=start, periods=n)

    vol_scale = np.ones(n)
    for i, br in enumerate(regime_breaks):
        if i % 2 == 0:
            vol_scale[br:] = 2.2
        else:
            vol_scale[br:] = 0.9

    daily_vol = annual_vol / np.sqrt(252)
    rets = rng.normal(loc=drift / 252, scale=daily_vol, size=n) * vol_scale
    # Inject mild autocorrelation in calm regimes for trend strategies.
    for t in range(1, n):
        if vol_scale[t] < 1.5:
            rets[t] += 0.15 * rets[t - 1]

    close = 100 * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[close[0]], close[:-1]])
    noise = rng.uniform(0.001, 0.006, size=n)
    high = np.maximum(open_, close) * (1 + noise)
    low = np.minimum(open_, close) * (1 - noise)
    volume = rng.integers(100_000, 500_000, size=n).astype(float)

    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )
