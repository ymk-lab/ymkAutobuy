#!/usr/bin/env python3
"""Wire LiveTradingLoop to LongbridgeBrokerAdapter in dry-run mode.

Uses synthetic panel history (no API keys required). This validates the
order path end-to-end without sending real orders.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.brokers.longbridge import LongbridgeBrokerAdapter
from qresearch.data.panel import generate_synthetic_panel
from qresearch.live.feed import HistoricalReplayFeed
from qresearch.live.loop import LiveConfig, LiveTradingLoop
from qresearch.portfolio.risk import RiskBudgetConfig
from qresearch.strategy.multi import CrossSectionalMomentumStrategy


def main() -> None:
    # Use Longbridge-like symbols even for synthetic data.
    panel = generate_synthetic_panel(("AAA.US", "BBB.US", "CCC.US"), n=180, seed=9)
    broker = LongbridgeBrokerAdapter(dry_run=True, initial_cash=100_000, currency="USD")

    result = LiveTradingLoop(
        feed=HistoricalReplayFeed(panel),
        strategy=CrossSectionalMomentumStrategy(lookback=10, top_fraction=0.34),
        broker=broker,
        risk_config=RiskBudgetConfig(
            vol_lookback=10,
            invert_vol=True,
            target_gross=1.0,
            max_weight=0.5,
            allow_short=False,
        ),
        config=LiveConfig(min_history=40, max_drawdown=0.5),
    ).run()

    print("=== Longbridge dry-run live loop ===")
    print(result.summary().round(4).to_string())
    print(f"fills: {len(result.fills)} (all dry-*)")
    if result.fills:
        print("sample fill:", result.fills[0])
    print("final positions:", broker.get_positions())
    print("final cash:", round(broker.get_cash(), 2))


if __name__ == "__main__":
    main()
