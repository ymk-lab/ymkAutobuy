from __future__ import annotations

from qresearch.backtest.engine import BacktestEngine
from qresearch.data.synthetic import generate_synthetic_ohlcv
from qresearch.strategy.examples import RegimeAwareTrendStrategy, SMACrossoverStrategy
from qresearch.validation.param_search import (
    expand_grid,
    grid_search,
    walk_forward_grid_search,
)


def test_expand_grid_count():
    grid = expand_grid({"fast": [5, 10], "slow": [20, 30, 40]})
    assert len(grid) == 6


def test_grid_search_picks_finite_best():
    data = generate_synthetic_ohlcv(n=300, seed=21)
    engine = BacktestEngine()

    def builder(params):
        return SMACrossoverStrategy(fast=params["fast"], slow=params["slow"])

    result = grid_search(
        data,
        builder,
        engine,
        {"fast": [5, 10], "slow": [20, 40]},
        score_key="sharpe",
    )
    assert "fast" in result.best_params
    assert "slow" in result.best_params
    assert len(result.trials) == 4
    board = result.leaderboard()
    assert board.iloc[0]["sharpe"] >= board.iloc[-1]["sharpe"]


def test_walk_forward_grid_search_records_params():
    data = generate_synthetic_ohlcv(n=500, seed=22)

    def builder(params):
        return RegimeAwareTrendStrategy(
            fast=params["fast"],
            slow=params["slow"],
            high_vol_weight=params["high_vol_weight"],
        )

    wf, selections = walk_forward_grid_search(
        data,
        builder,
        BacktestEngine(),
        {
            "fast": [5, 10],
            "slow": [30, 40],
            "high_vol_weight": [0.0],
        },
        train_size=200,
        test_size=50,
        step_size=50,
    )
    assert len(wf.folds) == len(selections)
    assert "param_fast" in selections.columns
    assert "oos_sharpe" in selections.columns
    assert selections["param_fast"].notna().all()
