#!/usr/bin/env python3
"""Generate a research-ready sample OHLCV CSV under examples/data/."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.data.loader import save_ohlcv_csv
from qresearch.data.synthetic import generate_synthetic_ohlcv


def main() -> None:
    out = ROOT / "examples" / "data" / "sample_ohlcv.csv"
    data = generate_synthetic_ohlcv(n=750, seed=7, regime_breaks=(250, 500))
    path = save_ohlcv_csv(data, out)
    print(f"Wrote {len(data)} bars → {path}")


if __name__ == "__main__":
    main()
