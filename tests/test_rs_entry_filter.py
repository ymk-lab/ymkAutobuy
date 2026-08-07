from __future__ import annotations

import numpy as np
import pandas as pd

from qresearch.strategy.base import Strategy
from qresearch.strategy.relative_strength import RelativeStrengthEntryFilter


class ScriptedBase(Strategy):
    name = "scripted"

    def __init__(self, signal: pd.Series) -> None:
        self._signal = signal

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        return self._signal.reindex(data.index).fillna(0.0)


def _frame(n: int = 40) -> tuple[pd.DataFrame, pd.Series]:
    idx = pd.bdate_range("2024-01-01", periods=n)
    # Stock drifts up; benchmark flat → positive excess after warmup
    stock = 100 * (1.01 ** np.arange(n))
    bench = pd.Series(100.0, index=idx)
    data = pd.DataFrame(
        {
            "open": stock,
            "high": stock * 1.01,
            "low": stock * 0.99,
            "close": stock,
            "volume": 1_000_000.0,
        },
        index=idx,
    )
    return data, bench


def test_rs_blocks_entry_but_not_exit():
    data, bench = _frame(50)
    # Base wants long from bar 25 to 40, then flat
    raw = pd.Series(0.0, index=data.index)
    raw.iloc[25:41] = 1.0

    # Force excess below threshold until bar 30 by using huge threshold early,
    # then normal 5% — easier: patch via high threshold then low.
    # Use threshold=0.05; with strong uptrend excess becomes large after window.
    strat = RelativeStrengthEntryFilter(
        base=ScriptedBase(raw),
        benchmark_close=bench,
        threshold=0.05,
        window=20,
    )
    sig = strat.generate_signals(data)

    # Before enough RS / while blocked, may stay flat even if base long
    # Once entered, stays long through base-long window even if we later
    # couldn't newly enter — verify exit follows base at 41.
    assert sig.iloc[41] == 0.0

    # Find first entry
    entered = sig[sig > 0]
    assert len(entered) > 0
    first_entry = entered.index[0]
    # All bars from first entry until base exit should remain long
    hold = sig.loc[first_entry : raw.index[40]]
    assert (hold > 0).all()


def test_without_rs_cannot_enter_when_excess_negative():
    idx = pd.bdate_range("2024-01-01", periods=40)
    # Stock flat, benchmark up → negative excess
    stock = pd.Series(100.0, index=idx)
    bench = 100 * (1.02 ** np.arange(40))
    data = pd.DataFrame(
        {
            "open": stock,
            "high": stock,
            "low": stock,
            "close": stock,
            "volume": 1.0,
        },
        index=idx,
    )
    raw = pd.Series(1.0, index=idx)
    sig = RelativeStrengthEntryFilter(
        ScriptedBase(raw),
        pd.Series(bench, index=idx),
        threshold=0.05,
        window=10,
    ).generate_signals(data)
    assert (sig == 0.0).all()
