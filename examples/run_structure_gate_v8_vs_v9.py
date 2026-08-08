#!/usr/bin/env python3
"""Compare Structure Gate v8 vs v9 across books."""

from __future__ import annotations

import argparse
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

OUT = ROOT / "examples" / "data" / "structure_gate_v8_vs_v9"
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("books", nargs="*", default=DEFAULT_BOOKS)
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default="2026-08-07")
    args = ap.parse_args()
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    books = [b.strip().upper() for b in args.books] or DEFAULT_BOOKS

    fees = FutuUsEquityFees(slippage_bps=3.0)
    variants = {"v8": StructureGateConfig.v8(), "v9": StructureGateConfig.v9()}
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for book in books:
        if book not in BOOKS:
            print(f"skip unknown {book}")
            continue
        for name, cfg in variants.items():
            print(f"\n##### {book} / {name} #####")
            rep = run_book(
                book,
                fees,
                cfg,
                start=start,
                end=end,
                out_root=OUT / name,
            )
            sg = rep["structure_gate"]
            meta_path = OUT / name / book.lower() / "structure_meta.csv"
            trades_path = OUT / name / book.lower() / "trades.csv"
            mild_top_cov = 0.0
            if meta_path.is_file():
                meta = pd.read_csv(meta_path, index_col=0)
                if "mild_top" in meta.columns:
                    mild_top_cov = float(meta["mild_top"].fillna(0).mean() * 100)
            n_trades = (
                int(len(pd.read_csv(trades_path))) if trades_path.is_file() else 0
            )
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
                    "n_trades": n_trades,
                    "cash_pct": rep["mode_distribution"].get("cash", 0.0) * 100,
                    "bench_pct": rep["mode_distribution"].get("bench", 0.0) * 100,
                    "mild_top_cov": mild_top_cov,
                }
            )

    df = pd.DataFrame(rows)
    print("\n=== v8 vs v9 ===")
    print(f"window={start.date()}..{end.date()}")
    print(
        df[
            [
                "book",
                "variant",
                "total_return",
                "max_drawdown",
                "vs_bh_pp",
                "soft_pass",
                "hard_pass",
                "n_trades",
                "cash_pct",
                "mild_top_cov",
            ]
        ].to_string(index=False, float_format=lambda x: f"{x:.4f}")
    )
    soft = df.groupby("variant")["soft_pass"].sum()
    hard = df.groupby("variant")["hard_pass"].sum()
    a = df[df.variant == "v8"].set_index("book")
    b = df[df.variant == "v9"].set_index("book")
    delta = (b["vs_bh_pp"] - a["vs_bh_pp"]).rename("delta_vs_bh_pp")
    trade_delta = (b["n_trades"] - a["n_trades"]).rename("delta_trades")
    print("soft:", soft.to_dict(), "hard:", hard.to_dict())
    print("delta vs_bh_pp (v9-v8):\n", delta.round(2).to_string())
    print("delta n_trades (v9-v8):\n", trade_delta.to_string())
    print(
        f"better_vs_bh={int((delta > 0).sum())}/{len(delta)} "
        f"mean_delta={delta.mean():+.2f}pp "
        f"mean_trade_delta={trade_delta.mean():+.1f}"
    )
    payload = {
        "window": [str(start.date()), str(end.date())],
        "v9": {
            "sticky_enter_trail": -0.065,
            "sticky_exit_trail": -0.045,
            "sma50_hysteresis": 0.005,
            "mild_top_enabled": True,
            "bench_slippage_bps": 3.0,
            "stock_slippage_bps": 8.0,
        },
        "soft_pass": soft.to_dict(),
        "hard_pass": hard.to_dict(),
        "delta_vs_bh_pp": delta.to_dict(),
        "delta_n_trades": trade_delta.to_dict(),
        "rows": rows,
    }
    (OUT / "compare_summary.json").write_text(
        json.dumps(payload, indent=2, default=float) + "\n"
    )
    print(f"wrote {OUT / 'compare_summary.json'}")


if __name__ == "__main__":
    main()
