#!/usr/bin/env python3
"""Read-only Longbridge smoke test: balances, positions, optional quotes.

Requires:
  LONGBRIDGE_APP_KEY
  LONGBRIDGE_APP_SECRET
  LONGBRIDGE_ACCESS_TOKEN

Never submits orders.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.brokers.longbridge import (
    LongbridgeBrokerAdapter,
    has_longbridge_credentials,
    load_longbridge_panel,
)


def main() -> None:
    if not has_longbridge_credentials():
        print(
            "Missing credentials. Export LONGBRIDGE_APP_KEY / "
            "LONGBRIDGE_APP_SECRET / LONGBRIDGE_ACCESS_TOKEN"
        )
        print("See .env.example")
        sys.exit(2)

    currency = os.getenv("QRESEARCH_LB_CURRENCY", "HKD")
    broker = LongbridgeBrokerAdapter.from_env(dry_run=True, currency=currency)
    print("currency:", currency)
    print("cash available:", broker.get_cash())
    print("positions:", broker.get_positions())

    symbols = [
        s.strip()
        for s in os.getenv("QRESEARCH_LB_SYMBOLS", "700.HK,AAPL.US").split(",")
        if s.strip()
    ]
    if broker.quote_ctx is not None and symbols:
        print("quotes:")
        for q in broker.quote_ctx.quote(symbols):
            print(f"  {q.symbol}: last={q.last_done} open={q.open} vol={q.volume}")

        count = int(os.getenv("QRESEARCH_LB_BARS", "30"))
        panel = load_longbridge_panel(symbols, quote_ctx=broker.quote_ctx, count=count)
        for sym, df in panel.items():
            print(f"history {sym}: {len(df)} bars, last close={df['close'].iloc[-1]:.4f}")


if __name__ == "__main__":
    main()
