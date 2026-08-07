"""Train-window parameter search for walk-forward research loops."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any, Callable

import pandas as pd

from qresearch.backtest.engine import BacktestEngine
from qresearch.metrics.performance import summarize_performance
from qresearch.strategy.base import Strategy
from qresearch.validation.walk_forward import WalkForwardResult, walk_forward


@dataclass(frozen=True)
class ParamTrial:
    params: dict[str, Any]
    stats: dict[str, float]


@dataclass
class ParamSearchResult:
    best_params: dict[str, Any]
    best_score: float
    trials: list[ParamTrial]
    score_key: str

    def leaderboard(self) -> pd.DataFrame:
        rows = []
        for t in self.trials:
            row = dict(t.params)
            row.update(t.stats)
            rows.append(row)
        frame = pd.DataFrame(rows)
        if not frame.empty and self.score_key in frame.columns:
            frame = frame.sort_values(self.score_key, ascending=False)
        return frame.reset_index(drop=True)


def expand_grid(param_grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    if not param_grid:
        return [{}]
    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]
    return [dict(zip(keys, combo)) for combo in product(*values)]


def grid_search(
    train_data: pd.DataFrame,
    strategy_builder: Callable[[dict[str, Any]], Strategy],
    engine: BacktestEngine,
    param_grid: dict[str, list[Any]],
    *,
    score_key: str = "sharpe",
    min_bars: int = 40,
) -> ParamSearchResult:
    """Exhaustive grid search on a train window only.

    Scores each candidate by running a full backtest on `train_data`.
    """
    if len(train_data) < min_bars:
        raise ValueError(f"train_data too short for search: {len(train_data)} < {min_bars}")

    trials: list[ParamTrial] = []
    best_params: dict[str, Any] | None = None
    best_score = float("-inf")

    for params in expand_grid(param_grid):
        strategy = strategy_builder(params)
        result = engine.run(train_data, strategy)
        score = float(result.stats.get(score_key, float("-inf")))
        trials.append(ParamTrial(params=params, stats=result.stats))
        if score > best_score:
            best_score = score
            best_params = params

    assert best_params is not None
    return ParamSearchResult(
        best_params=best_params,
        best_score=best_score,
        trials=trials,
        score_key=score_key,
    )


def walk_forward_grid_search(
    data: pd.DataFrame,
    strategy_builder: Callable[[dict[str, Any]], Strategy],
    engine: BacktestEngine,
    param_grid: dict[str, list[Any]],
    *,
    train_size: int = 252,
    test_size: int = 63,
    step_size: int | None = None,
    score_key: str = "sharpe",
) -> tuple[WalkForwardResult, pd.DataFrame]:
    """Walk-forward where each fold retunes params on train, then tests OOS.

    Returns:
    - WalkForwardResult for OOS performance
    - DataFrame of per-fold chosen params + train score
    """
    selections: list[dict[str, Any]] = []

    def factory(train: pd.DataFrame) -> Strategy:
        search = grid_search(
            train,
            strategy_builder,
            engine,
            param_grid,
            score_key=score_key,
        )
        row = {
            "train_end": str(train.index[-1].date()),
            "train_bars": len(train),
            "train_score": search.best_score,
            "score_key": score_key,
            **{f"param_{k}": v for k, v in search.best_params.items()},
        }
        selections.append(row)
        return strategy_builder(search.best_params)

    wf = walk_forward(
        data,
        factory,
        engine,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
    )
    # Align fold ids into selection table
    for i, row in enumerate(selections):
        row["fold"] = i
        if i < len(wf.folds):
            row["test_end"] = wf.folds[i]["test_end"]
            row["oos_sharpe"] = wf.folds[i]["test_stats"].get("sharpe", float("nan"))
            row["oos_total_return"] = wf.folds[i]["test_stats"].get(
                "total_return", float("nan")
            )

    return wf, pd.DataFrame(selections)
