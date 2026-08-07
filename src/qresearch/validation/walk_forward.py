"""Walk-forward validation helpers for research honesty."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from qresearch.backtest.engine import BacktestEngine, BacktestResult
from qresearch.strategy.base import Strategy


@dataclass
class WalkForwardResult:
    folds: list[dict]
    oos_returns: pd.Series
    oos_equity: pd.Series
    combined_stats: dict[str, float]

    def summary(self) -> pd.DataFrame:
        rows = []
        for f in self.folds:
            row = {"fold": f["fold"], "train_end": f["train_end"], "test_end": f["test_end"]}
            row.update(f["test_stats"])
            rows.append(row)
        return pd.DataFrame(rows)


def walk_forward(
    data: pd.DataFrame,
    strategy_factory: Callable[[pd.DataFrame], Strategy],
    engine: BacktestEngine,
    *,
    train_size: int = 252,
    test_size: int = 63,
    step_size: int | None = None,
) -> WalkForwardResult:
    """Anchored expanding walk-forward with purged train/test split.

    For each fold:
    - train window: [0, train_end)
    - test window:  [train_end, train_end + test_size)
    Strategy may fit only on train data via strategy_factory(train_df).
    """
    if train_size <= 1 or test_size <= 0:
        raise ValueError("train_size/test_size invalid")
    step = step_size or test_size
    n = len(data)
    if n < train_size + test_size:
        raise ValueError("not enough data for one walk-forward fold")

    from qresearch.metrics.performance import summarize_performance

    folds: list[dict] = []
    oos_parts: list[pd.Series] = []
    oos_turn_parts: list[pd.Series] = []
    oos_pos_parts: list[pd.Series] = []
    fold_id = 0
    start_test = train_size

    while start_test + test_size <= n:
        train = data.iloc[:start_test]
        test = data.iloc[start_test : start_test + test_size]
        strategy = strategy_factory(train)
        # Warm-start rolling features with train history; score only OOS bars.
        warm = pd.concat([train, test])
        result: BacktestResult = engine.run(warm, strategy)
        oos = result.returns.loc[test.index]
        oos_turn = result.turnover.loc[test.index]
        oos_pos = result.positions.loc[test.index]
        oos_eq = (1.0 + oos).cumprod()

        test_stats = summarize_performance(
            returns=oos,
            equity=oos_eq * engine.initial_capital,
            turnover=oos_turn,
            positions=oos_pos,
        )
        folds.append(
            {
                "fold": fold_id,
                "train_end": str(train.index[-1].date()),
                "test_end": str(test.index[-1].date()),
                "test_stats": test_stats,
            }
        )
        oos_parts.append(oos)
        oos_turn_parts.append(oos_turn)
        oos_pos_parts.append(oos_pos)
        fold_id += 1
        start_test += step

    if not oos_parts:
        raise ValueError("no walk-forward folds produced")

    oos_returns = pd.concat(oos_parts).sort_index()
    oos_turnover = pd.concat(oos_turn_parts).sort_index()
    oos_positions = pd.concat(oos_pos_parts).sort_index()
    # Drop duplicate indexes if windows overlapped (step < test_size)
    keep = ~oos_returns.index.duplicated(keep="first")
    oos_returns = oos_returns[keep]
    oos_turnover = oos_turnover[keep]
    oos_positions = oos_positions[keep]
    oos_equity = (1.0 + oos_returns).cumprod() * engine.initial_capital

    combined = summarize_performance(
        returns=oos_returns,
        equity=oos_equity,
        turnover=oos_turnover,
        positions=oos_positions,
    )
    return WalkForwardResult(
        folds=folds,
        oos_returns=oos_returns.rename("oos_returns"),
        oos_equity=oos_equity.rename("oos_equity"),
        combined_stats=combined,
    )
