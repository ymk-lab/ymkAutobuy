"""Unit tests for Emerging RS Wave book primitives."""

from __future__ import annotations

import numpy as np
import pandas as pd

from qresearch.strategy.emerging_rs_wave import EmergingRSWaveBook, market_gate


def test_market_gates_shapes():
    idx = pd.bdate_range("2024-01-01", periods=260)
    # gentle uptrend
    close = pd.Series(100 + np.arange(len(idx)) * 0.1, index=idx)
    for g in ("G1", "G2", "G3", "G4"):
        gate = market_gate(close, g)
        assert len(gate) == len(close)
        assert gate.dtype == bool


def test_single_name_slot_never_two_names():
    idx = pd.bdate_range("2023-01-01", periods=300)
    rng = np.random.default_rng(0)
    # QQQ flat-ish
    qqq = pd.Series(400 + np.cumsum(rng.normal(0, 0.5, len(idx))), index=idx)
    # A lags then bursts above QQQ; B stays weak
    a = qqq * 0.98
    a.iloc[200:230] = a.iloc[200:230].values * np.linspace(1.0, 1.15, 30)
    b = qqq * 0.95
    closes = pd.DataFrame({"AAA": a, "BBB": b})
    book = EmergingRSWaveBook(gate="G3")
    w, log = book.generate_weights(closes, qqq)
    active = (w.abs() > 1e-12).sum(axis=1)
    assert int(active.max()) <= 1
