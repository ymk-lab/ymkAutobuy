#!/usr/bin/env python3
"""Multi-asset momentum + risk budget backtest, with paper replay check."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from qresearch.backtest.costs import CostModel
from qresearch.backtest.multi_engine import MultiBacktestEngine
from qresearch.data.panel import generate_synthetic_panel, panel_close, save_panel_csv_dir
from qresearch.paper.broker import replay_paper_from_weights
from qresearch.portfolio.risk import RiskBudgetConfig
from qresearch.strategy.multi import CrossSectionalMomentumStrategy


def main() -> None:
    panel = generate_synthetic_panel(("AAA", "BBB", "CCC", "DDD"), n=750, seed=7)
    out_dir = ROOT / "examples" / "data" / "panel"
    save_panel_csv_dir(panel, out_dir)

    engine = MultiBacktestEngine(
        cost_model=CostModel(fee_bps=1.0, slippage_bps=3.0),
        risk_config=RiskBudgetConfig(
            vol_lookback=20,
            invert_vol=True,
            target_gross=1.0,
            target_vol=0.12,
            max_weight=0.45,
            allow_short=False,
        ),
    )
    strategy = CrossSectionalMomentumStrategy(lookback=20, top_fraction=0.5)
    result = engine.run(panel, strategy)

    print("=== Multi-asset backtest ===")
    print(result.summary().round(4).to_string())

    closes = panel_close(panel)
    paper_eq = replay_paper_from_weights(
        result.weights,
        closes,
        initial_capital=engine.initial_capital,
        cost_model=engine.cost_model,
    )
    # Compare overlapping equity path
    aligned = pd.concat(
        [result.equity.rename("backtest"), paper_eq.rename("paper")],
        axis=1,
    ).dropna()
    rel_err = (aligned["paper"] / aligned["backtest"] - 1.0).abs()
    print("\n=== Paper alignment ===")
    print(f"bars compared: {len(aligned)}")
    print(f"max relative equity error: {rel_err.max():.2e}")
    print(f"final backtest equity: {aligned['backtest'].iloc[-1]:.2f}")
    print(f"final paper equity:    {aligned['paper'].iloc[-1]:.2f}")
    print(f"\nPanel CSV dir: {out_dir}")


if __name__ == "__main__":
    main()
