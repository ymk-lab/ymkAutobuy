#!/usr/bin/env python3
"""Run a baseline SMA crossover research backtest on synthetic data."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.backtest.costs import CostModel
from qresearch.backtest.engine import BacktestEngine
from qresearch.data.synthetic import generate_synthetic_ohlcv
from qresearch.strategy.examples import SMACrossoverStrategy


def main() -> None:
    data = generate_synthetic_ohlcv(n=750, seed=7)
    strategy = SMACrossoverStrategy(fast=10, slow=30)
    engine = BacktestEngine(
        initial_capital=100_000,
        cost_model=CostModel(fee_bps=1.0, slippage_bps=2.0),
        allow_short=False,
    )
    result = engine.run(data, strategy)

    print("=== SMA Crossover Backtest ===")
    print(result.summary().round(4).to_string())
    print("\nEquity head/tail:")
    print(result.equity.head(3))
    print(result.equity.tail(3))
    print(f"\nTrades: {len(result.trades)}")


if __name__ == "__main__":
    main()
