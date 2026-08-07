#!/usr/bin/env python3
"""Fetch live quotes via Longbridge CLI (OAuth login), no APP_KEY env needed."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

def main() -> None:
    if not shutil.which("longbridge"):
        print("longbridge CLI not found. Install: curl -sSL https://open.longbridge.com/longbridge/longbridge-terminal/install | sh")
        sys.exit(2)
    symbols = sys.argv[1:] or ["NVDA.US", "QQQ.US", "AAPL.US"]
    r = subprocess.run(
        ["longbridge", "quote", *symbols, "--format", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(r.stderr or r.stdout)
        sys.exit(r.returncode)
    data = json.loads(r.stdout)
    for q in data:
        print(
            f"{q['symbol']}: last={q['last']} open={q['open']} "
            f"high={q['high']} low={q['low']} chg={q.get('change_percentage')}% "
            f"status={q.get('status')}"
        )

if __name__ == "__main__":
    main()
