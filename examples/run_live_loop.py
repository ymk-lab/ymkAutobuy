#!/usr/bin/env python3
"""Replay panel bars through the live loop + simulated broker."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.backtest.costs import CostModel
from qresearch.data.panel import generate_synthetic_panel
from qresearch.execution.sim_broker import SimBrokerAdapter
from qresearch.live.feed import HistoricalReplayFeed
from qresearch.live.loop import LiveConfig, LiveTradingLoop
from qresearch.portfolio.risk import RiskBudgetConfig
from qresearch.strategy.multi import CrossSectionalMomentumStrategy


def main() -> None:
    panel = generate_synthetic_panel(("AAA", "BBB", "CCC"), n=320, seed=11)
    feed = HistoricalReplayFeed(panel)
    broker = SimBrokerAdapter(
        initial_cash=100_000.0,
        cost_model=CostModel(fee_bps=1.0, slippage_bps=3.0),
        allow_short=False,
    )
    loop = LiveTradingLoop(
        feed=feed,
        strategy=CrossSectionalMomentumStrategy(lookback=15, top_fraction=0.34),
        broker=broker,
        risk_config=RiskBudgetConfig(
            vol_lookback=15,
            invert_vol=True,
            target_gross=1.0,
            target_vol=None,
            max_weight=0.5,
            allow_short=False,
        ),
        config=LiveConfig(min_history=40, rebalance_every=1, max_drawdown=0.35),
    )
    result = loop.run()

    print("=== Live loop (historical replay) ===")
    print(result.summary().round(4).to_string())
    print(f"\nstopped: {result.stopped} reason: {result.stop_reason}")
    print(f"fills: {len(result.fills)}")
    if result.fills:
        print("first fill:", result.fills[0])
        print("last fill:", result.fills[-1])
    print("\nEquity tail:")
    print(result.equity.tail(3))
    print("\nPosition weights tail:")
    print(result.weights.tail(3).round(4))


if __name__ == "__main__":
    main()
