#!/usr/bin/env python3
"""Compare plain trend vs regime-aware trend on synthetic regime-shifting data."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from qresearch.backtest.costs import CostModel
from qresearch.backtest.engine import BacktestEngine
from qresearch.data.synthetic import generate_synthetic_ohlcv
from qresearch.strategy.examples import RegimeAwareTrendStrategy, SMACrossoverStrategy
from qresearch.validation.walk_forward import walk_forward


def main() -> None:
    data = generate_synthetic_ohlcv(n=750, seed=7, regime_breaks=(250, 500))
    engine = BacktestEngine(
        cost_model=CostModel(fee_bps=1.0, slippage_bps=3.0),
        allow_short=False,
    )

    plain = engine.run(data, SMACrossoverStrategy(fast=10, slow=40))
    regime = engine.run(
        data,
        RegimeAwareTrendStrategy(fast=10, slow=40, high_vol_weight=0.0),
    )

    compare = pd.DataFrame(
        {
            "sma": plain.stats,
            "regime_aware": regime.stats,
        }
    )
    print("=== In-sample comparison ===")
    print(compare.round(4).to_string())

    def factory(_train: pd.DataFrame) -> RegimeAwareTrendStrategy:
        # Fixed params demo; replace with train-set tuning later.
        return RegimeAwareTrendStrategy(fast=10, slow=40, high_vol_weight=0.0)

    wf = walk_forward(
        data,
        factory,
        engine,
        train_size=252,
        test_size=63,
        step_size=63,
    )
    print("\n=== Walk-forward OOS folds ===")
    print(wf.summary().round(4).to_string(index=False))
    print("\n=== Walk-forward combined OOS ===")
    print(pd.Series(wf.combined_stats).round(4).to_string())


if __name__ == "__main__":
    main()
