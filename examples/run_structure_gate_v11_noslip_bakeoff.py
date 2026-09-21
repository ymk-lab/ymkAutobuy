#!/usr/bin/env python3
"""Bakeoff: Structure Gate v11 with default slippage vs slippage=0.

Keeps Futu broker commissions; only sets slippage_bps to 0.
Window matches the usual 1y blend: 2025-08-07 → 2026-08-07.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.strategy.regime_playbook import simulate_bench_bh
from qresearch.strategy.structure_gate import (
    V11_BOOK_WEIGHTS,
    StructureGateConfig,
    blend_structure_gate_books,
    simulate_structure_gate,
)
from run_emerging_rs_wave_gates import metrics  # type: ignore
from run_structure_gate_v11_blend import (  # type: ignore
    CAPITAL,
    align_panel,
    book_members,
    load_many,
)

OUT = ROOT / "examples" / "data" / "structure_gate_v11_noslip"
WEIGHTS = dict(V11_BOOK_WEIGHTS)
START = pd.Timestamp("2025-08-07")
END = pd.Timestamp("2026-08-07")


def run_case(name: str, frames: dict[str, pd.DataFrame], *, slippage_bps: float) -> dict:
    cfg = replace(
        StructureGateConfig.v11(),
        bench_slippage_bps=slippage_bps,
        stock_slippage_bps=slippage_bps,
    )
    book_sims = {}
    sleeves = []
    print(f"\n=== {name} slip={slippage_bps}bps {START.date()}→{END.date()} ===", flush=True)
    for book, w in WEIGHTS.items():
        sleeve_cap = CAPITAL * w
        bdf = frames[book].loc[:END]
        opens, closes = align_panel(frames, book_members(book), bdf.index)
        fees = FutuUsEquityFees(slippage_bps=slippage_bps)
        sim = simulate_structure_gate(
            opens,
            closes,
            bdf["open"],
            bdf["close"],
            capital=sleeve_cap,
            start=START,
            fees=fees,
            config=cfg,
            bench_volume=bdf["volume"] if "volume" in bdf.columns else None,
        )
        book_sims[book] = sim
        m = metrics(sim.equity, sleeve_cap)
        n_trades = int(len(sim.trades)) if sim.trades is not None else 0
        row = {
            "book": book,
            "total_return": m["total_return"],
            "max_drawdown": m["max_drawdown"],
            "sharpe": m["sharpe"],
            "n_trades": n_trades,
        }
        sleeves.append(row)
        print(
            f"  {book:4} SG={m['total_return']*100:7.2f}% maxDD={m['max_drawdown']*100:6.2f}% "
            f"Sharpe={m['sharpe']:.2f} trades={n_trades}",
            flush=True,
        )
        sim.equity.to_csv(OUT / f"equity_{name}_{book}.csv", header=["equity"])

    blended, _ = blend_structure_gate_books(book_sims, WEIGHTS, capital=CAPITAL)
    blended = blended.loc[START:END].dropna()
    m_b = metrics(blended, CAPITAL)
    spy = frames["SPY"]
    fees = FutuUsEquityFees(slippage_bps=slippage_bps)
    eq_bh = simulate_bench_bh(
        spy["open"], spy["close"], capital=CAPITAL, start=START, fees=fees
    ).reindex(blended.index).ffill()
    m_bh = metrics(eq_bh, CAPITAL)
    blended.to_csv(OUT / f"equity_{name}_blend.csv", header=["equity"])
    out = {
        "preset": name,
        "slippage_bps": slippage_bps,
        "note": "Futu commissions kept; only slippage_bps changed",
        "start": str(START.date()),
        "end": str(END.date()),
        "structure_gate_total_return": m_b["total_return"],
        "structure_gate_max_drawdown": m_b["max_drawdown"],
        "structure_gate_sharpe": m_b["sharpe"],
        "spy_bh_total_return": m_bh["total_return"],
        "vs_spy_pp": (m_b["total_return"] - m_bh["total_return"]) * 100,
        "sleeves": sleeves,
    }
    print(
        f"  BLEND SG={m_b['total_return']*100:.2f}% maxDD={m_b['max_drawdown']*100:.2f}% "
        f"Sharpe={m_b['sharpe']:.2f} vsSPY={out['vs_spy_pp']:+.1f}pp",
        flush=True,
    )
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    symbols: list[str] = []
    seen: set[str] = set()
    for book in WEIGHTS:
        for s in [book, *book_members(book)]:
            if s not in seen:
                seen.add(s)
                symbols.append(s)
    print(f"Loading {len(symbols)} symbols…", flush=True)
    frames = load_many(symbols)
    for b in WEIGHTS:
        if b not in frames:
            raise SystemExit(f"missing {b}")

    with_slip = run_case("v11_slip3", frames, slippage_bps=3.0)
    no_slip = run_case("v11_noslip", frames, slippage_bps=0.0)
    delta = {
        "total_return_pp": (no_slip["structure_gate_total_return"] - with_slip["structure_gate_total_return"]) * 100,
        "max_drawdown_pp": (no_slip["structure_gate_max_drawdown"] - with_slip["structure_gate_max_drawdown"]) * 100,
        "sharpe_delta": no_slip["structure_gate_sharpe"] - with_slip["structure_gate_sharpe"],
        "sleeve_return_pp": {
            a["book"]: (b["total_return"] - a["total_return"]) * 100
            for a, b in zip(with_slip["sleeves"], no_slip["sleeves"])
        },
    }
    summary = {"with_slip_3bps": with_slip, "no_slip": no_slip, "noslip_minus_slip3": delta}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("\n=== noslip - slip3bps ===", flush=True)
    print(
        f"return {delta['total_return_pp']:+.2f}pp  maxDD {delta['max_drawdown_pp']:+.2f}pp  "
        f"Sharpe {delta['sharpe_delta']:+.3f}",
        flush=True,
    )
    print("sleeve Δpp:", {k: round(v, 2) for k, v in delta["sleeve_return_pp"].items()}, flush=True)
    print(f"wrote {OUT / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
