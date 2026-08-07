#!/usr/bin/env python3
"""Load CSV → walk-forward grid search → print OOS report."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.backtest.costs import CostModel
from qresearch.backtest.engine import BacktestEngine
from qresearch.data.loader import load_ohlcv_csv, save_ohlcv_csv
from qresearch.data.synthetic import generate_synthetic_ohlcv
from qresearch.strategy.examples import RegimeAwareTrendStrategy
from qresearch.validation.param_search import walk_forward_grid_search


def ensure_sample_csv(path: Path) -> Path:
    if path.exists():
        return path
    data = generate_synthetic_ohlcv(n=750, seed=7, regime_breaks=(250, 500))
    return save_ohlcv_csv(data, path)


def main() -> None:
    csv_path = ensure_sample_csv(ROOT / "examples" / "data" / "sample_ohlcv.csv")
    data = load_ohlcv_csv(csv_path)
    print(f"Loaded {len(data)} bars from {csv_path}")
    print(f"Range: {data.index[0].date()} → {data.index[-1].date()}")

    engine = BacktestEngine(
        cost_model=CostModel(fee_bps=1.0, slippage_bps=3.0),
        allow_short=False,
    )

    param_grid = {
        "fast": [5, 10, 15],
        "slow": [30, 40, 60],
        "high_vol_weight": [0.0, 0.25],
    }

    def builder(params: dict) -> RegimeAwareTrendStrategy:
        # Guard invalid combos inside builder
        fast = int(params["fast"])
        slow = int(params["slow"])
        if fast >= slow:
            # Degenerate params: force a valid ordering for search continuity
            fast, slow = min(fast, slow - 1), slow
        return RegimeAwareTrendStrategy(
            fast=fast,
            slow=slow,
            high_vol_weight=float(params["high_vol_weight"]),
        )

    wf, selections = walk_forward_grid_search(
        data,
        builder,
        engine,
        param_grid,
        train_size=252,
        test_size=63,
        step_size=63,
        score_key="sharpe",
    )

    print("\n=== Per-fold selected params (train Sharpe → OOS) ===")
    cols = [
        "fold",
        "train_end",
        "test_end",
        "param_fast",
        "param_slow",
        "param_high_vol_weight",
        "train_score",
        "oos_sharpe",
        "oos_total_return",
    ]
    print(selections[cols].round(4).to_string(index=False))

    print("\n=== Combined OOS ===")
    print(wf.summary().round(4).to_string(index=False))
    print("\nOOS aggregate:")
    for k, v in wf.combined_stats.items():
        print(f"  {k}: {v:.4f}")


if __name__ == "__main__":
    main()
