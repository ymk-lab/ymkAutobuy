#!/usr/bin/env python3
"""Compare structure-gate v8 vs v8.1 (mild_vol_adaptive=True) across books."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.strategy.structure_gate import StructureGateConfig
from run_structure_gate_bakeoff import BOOKS, run_book  # type: ignore

OUT = ROOT / "examples" / "data" / "structure_gate_v8_vs_v81"
DEFAULT_BOOKS = [
    "QQQ",
    "SMH",
    "SOXX",
    "SPY",
    "DIA",
    "IWM",
    "XLF",
    "XLK",
    "XBI",
    "XLE",
]
VARIANTS = {
    "v8": StructureGateConfig(),
    "v8.1": StructureGateConfig(mild_vol_adaptive=True),
}


def main() -> None:
    books = [a.strip().upper() for a in sys.argv[1:] if not a.startswith("--")]
    if not books:
        books = DEFAULT_BOOKS
    start = pd.Timestamp("2025-01-01")
    end = pd.Timestamp("2026-08-07")
    for i, a in enumerate(sys.argv[1:], 1):
        if a == "--start" and i < len(sys.argv) - 1:
            start = pd.Timestamp(sys.argv[i + 1])
        if a == "--end" and i < len(sys.argv) - 1:
            end = pd.Timestamp(sys.argv[i + 1])
    # strip flag values from books list
    cleaned: list[str] = []
    skip = False
    for a in sys.argv[1:]:
        if skip:
            skip = False
            continue
        if a in ("--start", "--end"):
            skip = True
            continue
        cleaned.append(a.strip().upper())
    books = cleaned or DEFAULT_BOOKS

    fees = FutuUsEquityFees(slippage_bps=3.0)
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for book in books:
        if book not in BOOKS:
            print(f"skip unknown {book}")
            continue
        for name, cfg in VARIANTS.items():
            print(f"\n##### {book} / {name} #####")
            out_root = OUT / name.replace(".", "_")
            rep = run_book(
                book, fees, cfg, start=start, end=end, out_root=out_root
            )
            sg = rep["structure_gate"]
            rows.append(
                {
                    "book": book,
                    "variant": name,
                    "total_return": sg["total_return"],
                    "max_drawdown": sg["max_drawdown"],
                    "sharpe": sg["sharpe"],
                    "vs_bh_pp": rep["vs_bh_pp"],
                    "vs_ers_pp": rep["vs_ers_pp"],
                    "soft_pass": rep["soft_pass"],
                    "hard_pass": rep["hard_pass_beat_both"],
                    "gap_vs_better_pp": rep["gap_vs_better_pp"],
                    "cash_pct": rep["mode_distribution"].get("cash", 0.0) * 100,
                    "bench_pct": rep["mode_distribution"].get("bench", 0.0) * 100,
                }
            )

    df = pd.DataFrame(rows)
    pivot = df.pivot(index="book", columns="variant")
    soft = df.groupby("variant")["soft_pass"].sum()
    hard = df.groupby("variant")["hard_pass"].sum()
    med_vs = df.groupby("variant")["vs_bh_pp"].median()
    min_vs = df.groupby("variant")["vs_bh_pp"].min()

    print("\n=== v8 vs v8.1 ===")
    print(f"window={start.date()}..{end.date()} n_books={len(books)}")
    show = df[
        [
            "book",
            "variant",
            "total_return",
            "max_drawdown",
            "vs_bh_pp",
            "soft_pass",
            "hard_pass",
            "cash_pct",
        ]
    ]
    print(show.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nsoft_pass counts:", soft.to_dict())
    print("hard_pass counts:", hard.to_dict())
    print("median vs_bh_pp:", med_vs.round(2).to_dict())
    print("min vs_bh_pp:", min_vs.round(2).to_dict())

    # paired deltas v8.1 - v8
    a = df[df.variant == "v8"].set_index("book")
    b = df[df.variant == "v8.1"].set_index("book")
    delta = (b["vs_bh_pp"] - a["vs_bh_pp"]).rename("delta_vs_bh_pp")
    print("\ndelta vs_bh_pp (v8.1 - v8):")
    print(delta.round(2).to_string())
    print(
        f"better_vs_bh={int((delta > 0).sum())}/{len(delta)} "
        f"worse={int((delta < 0).sum())} "
        f"mean_delta={delta.mean():+.2f}pp"
    )

    payload = {
        "window": [str(start.date()), str(end.date())],
        "v8.1_diff": "StructureGateConfig(mild_vol_adaptive=True)",
        "soft_pass": soft.to_dict(),
        "hard_pass": hard.to_dict(),
        "median_vs_bh_pp": med_vs.to_dict(),
        "min_vs_bh_pp": min_vs.to_dict(),
        "delta_vs_bh_pp": delta.to_dict(),
        "rows": rows,
    }
    (OUT / "compare_summary.json").write_text(
        json.dumps(payload, indent=2, default=float) + "\n"
    )
    print(f"wrote {OUT / 'compare_summary.json'}")


if __name__ == "__main__":
    main()
