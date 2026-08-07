from __future__ import annotations

import pandas as pd

from qresearch.backtest.engine import BacktestEngine
from qresearch.data.synthetic import generate_synthetic_ohlcv
from qresearch.strategy.examples import SMACrossoverStrategy
from qresearch.validation.walk_forward import walk_forward


def test_walk_forward_produces_folds():
    data = generate_synthetic_ohlcv(n=500, seed=9)

    def factory(_train: pd.DataFrame) -> SMACrossoverStrategy:
        return SMACrossoverStrategy(fast=8, slow=21)

    wf = walk_forward(
        data,
        factory,
        BacktestEngine(),
        train_size=200,
        test_size=50,
        step_size=50,
    )
    assert len(wf.folds) >= 3
    assert len(wf.oos_returns) > 0
    summary = wf.summary()
    assert "sharpe" in summary.columns
    assert "fold" in summary.columns
