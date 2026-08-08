#!/usr/bin/env python3
"""v8 + book peak-equity DD hard stop at 12% — bakeoff across all books."""

from __future__ import annotations

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
    OUT as OUT_BASE,
    run_book,
)

OUT = ROOT / "examples" / "data" / "structure_gate_bakeoff_dd12"
DD_LIMIT = 0.12


def main() -> None:
    # Redirect bakeoff outputs into dd12 folder via monkeypatch of OUT in module.
    import run_structure_gate_bakeoff as bb  # type: ignore

    bb.OUT = OUT
    OUT.mkdir(parents=True, exist_ok=True)

    fees = FutuUsEquityFees(slippage_bps=3.0)
    cfg = StructureGateConfig(book_peak_dd_stop=DD_LIMIT, book_dd_reentry_confirm=3)
    books = [a.strip().upper() for a in sys.argv[1:]] or [
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
        dd_ok = dd >= -DD_LIMIT - 1e-12  # max_drawdown is negative
        r["dd_limit"] = DD_LIMIT
        r["dd_hard_pass"] = bool(dd_ok)
        r["hard_pass_with_dd"] = bool(r["hard_pass_beat_both"] and dd_ok)
        r["soft_pass_with_dd"] = bool(r["soft_pass"] and dd_ok)
        r["criteria"]["dd_hard"] = f"max_drawdown >= -{DD_LIMIT:.0%} (book peak stop)"
        (OUT / b.lower() / "bakeoff.json").write_text(
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
        "rule": "structure_gate_v8_dd12",
        "book_peak_dd_stop": DD_LIMIT,
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
            "v8 defaults + book equity peak DD hard stop at 12%; "
            "halt until non-cash signal confirms 3 days. In-window variant."
        ),
    }
    (OUT / "bakeoff_combined.json").write_text(
        json.dumps(combined, indent=2, default=float) + "\n"
    )
    print("\n=== COMBINED v8+DD12 ===")
    print(
        f"soft={soft_n}/{len(reports)} hard={hard_n}/{len(reports)} "
        f"dd<=12%={dd_n}/{len(reports)} soft&dd={soft_dd} hard&dd={hard_dd}"
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
