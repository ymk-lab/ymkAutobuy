#!/usr/bin/env python3
"""v8 + book peak-equity DD hard stop — bakeoff across all books.

Usage:
  python examples/run_structure_gate_bakeoff_dd12.py
  python examples/run_structure_gate_bakeoff_dd12.py --dd 0.15
  python examples/run_structure_gate_bakeoff_dd12.py --dd 0.15 QQQ SPY
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.strategy.structure_gate import StructureGateConfig
from run_structure_gate_bakeoff import (  # type: ignore
    SOFT_MAX_GAP_PP,
    run_book,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dd", type=float, default=0.12, help="book peak DD stop (e.g. 0.15)")
    ap.add_argument("books", nargs="*", help="books to run (default: all ten)")
    args = ap.parse_args()
    dd_limit = abs(float(args.dd))
    tag = f"dd{int(round(dd_limit * 100)):02d}"
    out = ROOT / "examples" / "data" / f"structure_gate_bakeoff_{tag}"

    import run_structure_gate_bakeoff as bb  # type: ignore

    bb.OUT = out
    out.mkdir(parents=True, exist_ok=True)

    fees = FutuUsEquityFees(slippage_bps=3.0)
    cfg = StructureGateConfig(book_peak_dd_stop=dd_limit, book_dd_reentry_confirm=3)
    books = [a.strip().upper() for a in args.books] or [
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
    reports = []
    for b in books:
        r = run_book(b, fees, cfg)
        dd = float(r["structure_gate"]["max_drawdown"])
        dd_ok = dd >= -dd_limit - 1e-12  # max_drawdown is negative
        r["dd_limit"] = dd_limit
        r["dd_hard_pass"] = bool(dd_ok)
        r["hard_pass_with_dd"] = bool(r["hard_pass_beat_both"] and dd_ok)
        r["soft_pass_with_dd"] = bool(r["soft_pass"] and dd_ok)
        r["criteria"]["dd_hard"] = f"max_drawdown >= -{dd_limit:.0%} (book peak stop)"
        (out / b.lower() / "bakeoff.json").write_text(
            json.dumps(r, indent=2, default=float) + "\n"
        )
        print(
            f"DD_HARD={r['dd_hard_pass']} HARD+DD={r['hard_pass_with_dd']} "
            f"SOFT+DD={r['soft_pass_with_dd']} | realized_dd={dd:.1%}"
        )
        reports.append(r)

    soft_n = sum(1 for r in reports if r["soft_pass"])
    hard_n = sum(1 for r in reports if r["hard_pass_beat_both"])
    dd_n = sum(1 for r in reports if r["dd_hard_pass"])
    soft_dd = sum(1 for r in reports if r["soft_pass_with_dd"])
    hard_dd = sum(1 for r in reports if r["hard_pass_with_dd"])
    combined = {
        "rule": f"structure_gate_v8_{tag}",
        "book_peak_dd_stop": dd_limit,
        "book_dd_reentry_confirm": cfg.book_dd_reentry_confirm,
        "soft_max_gap_pp": SOFT_MAX_GAP_PP,
        "counts": {
            "soft_pass": soft_n,
            "hard_pass": hard_n,
            "dd_hard_pass": dd_n,
            "soft_and_dd": soft_dd,
            "hard_and_dd": hard_dd,
            "n_books": len(reports),
        },
        "books": {r["book"]: r for r in reports},
        "note": (
            f"v8 defaults + book equity peak DD hard stop at {dd_limit:.0%}; "
            "halt until non-cash signal confirms 3 days. In-window variant."
        ),
    }
    (out / "bakeoff_combined.json").write_text(
        json.dumps(combined, indent=2, default=float) + "\n"
    )
    print(f"\n=== COMBINED v8+{tag.upper()} ===")
    print(
        f"soft={soft_n}/{len(reports)} hard={hard_n}/{len(reports)} "
        f"dd<={dd_limit:.0%}={dd_n}/{len(reports)} soft&dd={soft_dd} hard&dd={hard_dd}"
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
