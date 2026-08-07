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
from qresearch.brokers.longbridge.config import load_dotenv_if_present


def main() -> None:
    load_dotenv_if_present(ROOT / ".env")
    if not has_longbridge_credentials():
        print(
            "Missing credentials. Export LONGBRIDGE_APP_KEY / "
            "LONGBRIDGE_APP_SECRET / LONGBRIDGE_ACCESS_TOKEN"
        )
        print("Or copy .env.example → .env and fill values (never commit .env).")
        print("Get keys at https://open.longbridge.com/")
        sys.exit(2)

    currency = os.getenv("QRESEARCH_LB_CURRENCY", "USD")
    print("Connecting Longbridge (dry_run reads only; no orders)…")
    broker = LongbridgeBrokerAdapter.from_env(dry_run=True, currency=currency)
    print("currency:", currency)
    print("cash available:", broker.get_cash())
    print("positions:", broker.get_positions())

    symbols = [
        s.strip()
        for s in os.getenv("QRESEARCH_LB_SYMBOLS", "AAPL.US,QQQ.US,NVDA.US").split(",")
        if s.strip()
    ]
    if broker.quote_ctx is not None and symbols:
        print("quotes:")
        for q in broker.quote_ctx.quote(symbols):
            print(
                f"  {q.symbol}: last={q.last_done} open={q.open} "
                f"high={q.high} low={q.low} vol={q.volume}"
            )

        count = int(os.getenv("QRESEARCH_LB_BARS", "30"))
        panel = load_longbridge_panel(symbols, quote_ctx=broker.quote_ctx, count=count)
        for sym, df in panel.items():
            print(
                f"history {sym}: {len(df)} bars, "
                f"{df.index.min().date()}→{df.index.max().date()}, "
                f"last close={df['close'].iloc[-1]:.4f}"
            )
    print("OK — Longbridge connected.")


if __name__ == "__main__":
    main()
