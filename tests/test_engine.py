from __future__ import annotations

import pandas as pd
import pytest

from qresearch.backtest.costs import CostModel
from qresearch.backtest.engine import BacktestEngine
from qresearch.data.synthetic import generate_synthetic_ohlcv
from qresearch.strategy.base import Strategy
from qresearch.strategy.examples import SMACrossoverStrategy


class FlatStrategy(Strategy):
    name = "flat"

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        return pd.Series(0.0, index=data.index, name="signal")


class AlwaysLong(Strategy):
    name = "always_long"

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=data.index, name="signal")


def test_next_bar_execution_no_same_bar_edge():
    data = generate_synthetic_ohlcv(n=120, seed=1)
    engine = BacktestEngine(cost_model=CostModel(fee_bps=0, slippage_bps=0))
    result = engine.run(data, AlwaysLong())
    # First bar position must be 0 due to shift(1)
    assert result.positions.iloc[0] == 0.0
    assert result.positions.iloc[1] == 1.0


def test_flat_strategy_zero_turnover_after_start():
    data = generate_synthetic_ohlcv(n=100, seed=2)
    engine = BacktestEngine()
    result = engine.run(data, FlatStrategy())
    assert result.equity.iloc[-1] == pytest.approx(engine.initial_capital)
    assert result.turnover.sum() == pytest.approx(0.0)


def test_costs_reduce_equity_vs_zero_cost():
    data = generate_synthetic_ohlcv(n=300, seed=3)
    strategy = SMACrossoverStrategy(fast=5, slow=20)
    free = BacktestEngine(cost_model=CostModel(0, 0)).run(data, strategy)
    costly = BacktestEngine(cost_model=CostModel(10, 20)).run(data, strategy)
    assert costly.equity.iloc[-1] <= free.equity.iloc[-1]


def test_short_disabled_clips_negative():
    class ShortSignal(Strategy):
        name = "short"

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            return pd.Series(-1.0, index=data.index)

    data = generate_synthetic_ohlcv(n=80, seed=4)
    result = BacktestEngine(allow_short=False).run(data, ShortSignal())
    assert (result.positions >= 0).all()
