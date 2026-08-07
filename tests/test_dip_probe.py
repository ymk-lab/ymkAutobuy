from __future__ import annotations

import numpy as np
import pandas as pd

from qresearch.strategy.base import Strategy
from qresearch.strategy.dip_probe import DipProbeEntryFilter


class ScriptedBase(Strategy):
    name = "scripted"

    def __init__(self, signal: pd.Series) -> None:
        self._signal = signal

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        return self._signal.reindex(data.index).fillna(0.0)


def _ohlcv(close: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000.0,
        },
        index=close.index,
    )


def test_dip_then_upgrade_to_full():
    idx = pd.bdate_range("2024-01-01", periods=80)
    # Rise then drop 12% from peak, then base turns long
    close = pd.Series(100.0, index=idx)
    close.iloc[:40] = np.linspace(100, 120, 40)
    close.iloc[40:55] = np.linspace(120, 120 * 0.88, 15)  # ~12% DD
    close.iloc[55:] = np.linspace(120 * 0.88, 120 * 0.95, 25)

    raw = pd.Series(0.0, index=idx)
    raw.iloc[60:] = 1.0  # full signal later

    strat = DipProbeEntryFilter(
        base=ScriptedBase(raw),
        dip_threshold=0.10,
        dip_weight=0.25,
        drawdown_lookback=20,
        dip_stop=0.20,
    )
    sig = strat.generate_signals(_ohlcv(close))

    # Should probe before full signal
    dip_bars = sig.iloc[40:60]
    assert (dip_bars == 0.25).any()
    assert (sig.iloc[60:] == 1.0).all()


def test_dip_stop_cuts_probe():
    idx = pd.bdate_range("2024-01-01", periods=70)
    close = pd.Series(100.0, index=idx)
    close.iloc[:30] = 100.0
    close.iloc[30:40] = np.linspace(100, 90, 10)  # -10% → dip
    # Continue another 15% from ~90 → stop at 0.12 from entry
    close.iloc[40:] = np.linspace(90, 90 * 0.80, 30)

    raw = pd.Series(0.0, index=idx)  # never full signal
    strat = DipProbeEntryFilter(
        base=ScriptedBase(raw),
        dip_threshold=0.08,
        dip_weight=0.25,
        drawdown_lookback=15,
        dip_stop=0.12,
    )
    sig = strat.generate_signals(_ohlcv(close))
    assert (sig == 0.25).any()
    assert sig.iloc[-1] == 0.0


def test_full_signal_skips_dip():
    idx = pd.bdate_range("2024-01-01", periods=50)
    close = pd.Series(np.linspace(100, 110, 50), index=idx)
    raw = pd.Series(1.0, index=idx)
    sig = DipProbeEntryFilter(
        ScriptedBase(raw),
        dip_threshold=0.10,
        dip_weight=0.25,
        drawdown_lookback=20,
        dip_stop=0.12,
    ).generate_signals(_ohlcv(close))
    assert (sig == 1.0).all()
