#!/usr/bin/env python3
"""Bakeoff: Structure Gate v11 vs v12 (gap filter + earnings no-new-entry).

v12 execution overlays (next-open BUYs only):
  - |open/prev_close-1| ≥ 1% → half size
  - |open/prev_close-1| ≥ 2% → cancel entry that day
  - earnings date → cancel new entry (stocks; ETF benches rarely listed)
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
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

OUT = ROOT / "examples" / "data" / "structure_gate_v12_bakeoff"
WEIGHTS = dict(V11_BOOK_WEIGHTS)
START = pd.Timestamp("2025-08-07")
END = pd.Timestamp("2026-08-07")
EARNINGS_CACHE = OUT / "earnings_dates.json"


def _all_symbols() -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for book in WEIGHTS:
        for s in [book, *book_members(book)]:
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


def _fetch_one_earnings(sym: str) -> tuple[str, list[str]]:
    try:
        import yfinance as yf

        t = yf.Ticker(sym)
        ed = t.get_earnings_dates(limit=24)
        if ed is None or len(ed) == 0:
            return sym, []
        idx = pd.to_datetime(ed.index).tz_localize(None).normalize()
        return sym, sorted({d.strftime("%Y-%m-%d") for d in idx})
    except Exception:
        return sym, []


def load_earnings(symbols: list[str]) -> dict[str, set[pd.Timestamp]]:
    OUT.mkdir(parents=True, exist_ok=True)
    cached: dict[str, list[str]] = {}
    if EARNINGS_CACHE.is_file():
        cached = json.loads(EARNINGS_CACHE.read_text(encoding="utf-8"))
    missing = [s for s in symbols if s not in cached and s not in WEIGHTS]
    if missing:
        print(f"Fetching earnings dates for {len(missing)} symbols…", flush=True)
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {pool.submit(_fetch_one_earnings, s): s for s in missing}
            done = 0
            for fut in as_completed(futs):
                sym, dates = fut.result()
                cached[sym] = dates
                done += 1
                if done == 1 or done % 40 == 0 or done == len(missing):
                    print(f"  earnings [{done}/{len(missing)}] last={sym} n={len(dates)}", flush=True)
        EARNINGS_CACHE.write_text(json.dumps(cached, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out: dict[str, set[pd.Timestamp]] = {}
    for s, dates in cached.items():
        out[s] = {pd.Timestamp(d).normalize() for d in dates}
    return out


def run_preset(
    name: str,
    cfg: StructureGateConfig,
    frames: dict[str, pd.DataFrame],
    earnings: dict[str, set[pd.Timestamp]],
) -> dict:
    book_sims = {}
    sleeves = []
    skip_gap = 0
    skip_earn = 0
    shrink_n = 0
    buy_n = 0
    print(f"\n=== {name} {START.date()}→{END.date()} ===", flush=True)
    for book, w in WEIGHTS.items():
        sleeve_cap = CAPITAL * w
        bdf = frames[book].loc[:END]
        opens, closes = align_panel(frames, book_members(book), bdf.index)
        fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
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
            earnings_by_symbol=earnings if cfg.block_earnings_entries else None,
            bench_symbol=book,
        )
        book_sims[book] = sim
        tdf = sim.trades if isinstance(sim.trades, pd.DataFrame) else pd.DataFrame(sim.trades)
        if len(tdf):
            buy_n += int((tdf["side"] == "BUY").sum())
            if "reason" in tdf.columns:
                skip_gap += int(tdf["reason"].astype(str).str.contains("gap_cancel").sum())
                skip_earn += int(tdf["reason"].astype(str).str.contains("earnings_block").sum())
                shrink_n += int(tdf["reason"].astype(str).str.contains("gap_shrink").sum())
        m = metrics(sim.equity, sleeve_cap)
        row = {
            "book": book,
            "total_return": m["total_return"],
            "max_drawdown": m["max_drawdown"],
            "sharpe": m["sharpe"],
            "n_trades": int(len(tdf)),
            "n_buys": int((tdf["side"] == "BUY").sum()) if len(tdf) else 0,
        }
        sleeves.append(row)
        print(
            f"  {book:4} SG={m['total_return']*100:7.2f}% maxDD={m['max_drawdown']*100:6.2f}% "
            f"Sharpe={m['sharpe']:.2f} trades={row['n_trades']} buys={row['n_buys']}",
            flush=True,
        )
        sim.equity.to_csv(OUT / f"equity_{name}_{book}.csv", header=["equity"])
        if len(tdf):
            tdf.to_csv(OUT / f"trades_{name}_{book}.csv", index=False)

    blended, _ = blend_structure_gate_books(book_sims, WEIGHTS, capital=CAPITAL)
    blended = blended.loc[START:END].dropna()
    m_b = metrics(blended, CAPITAL)
    spy = frames["SPY"]
    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    eq_bh = simulate_bench_bh(spy["open"], spy["close"], capital=CAPITAL, start=START, fees=fees)
    eq_bh = eq_bh.reindex(blended.index).ffill()
    m_bh = metrics(eq_bh, CAPITAL)
    blended.to_csv(OUT / f"equity_{name}_blend.csv", header=["equity"])
    summary = {
        "preset": name,
        "start": str(START.date()),
        "end": str(END.date()),
        "weights": WEIGHTS,
        "structure_gate_total_return": m_b["total_return"],
        "structure_gate_max_drawdown": m_b["max_drawdown"],
        "structure_gate_sharpe": m_b["sharpe"],
        "spy_bh_total_return": m_bh["total_return"],
        "vs_spy_pp": (m_b["total_return"] - m_bh["total_return"]) * 100,
        "n_buys": buy_n,
        "n_gap_cancel": skip_gap,
        "n_gap_shrink": shrink_n,
        "n_earnings_block": skip_earn,
        "sleeves": sleeves,
        "config": {
            "exec_gap_shrink": cfg.exec_gap_shrink,
            "exec_gap_cancel": cfg.exec_gap_cancel,
            "exec_gap_shrink_weight": cfg.exec_gap_shrink_weight,
            "block_earnings_entries": cfg.block_earnings_entries,
        },
    }
    print(
        f"  BLEND SG={m_b['total_return']*100:.2f}% maxDD={m_b['max_drawdown']*100:.2f}% "
        f"Sharpe={m_b['sharpe']:.2f} vsSPY={summary['vs_spy_pp']:+.1f}pp "
        f"gap_cancel={skip_gap} gap_shrink={shrink_n} earn_block={skip_earn}",
        flush=True,
    )
    return summary


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    symbols = _all_symbols()
    print(f"Loading {len(symbols)} symbols…", flush=True)
    frames = load_many(symbols)
    for b in WEIGHTS:
        if b not in frames:
            raise SystemExit(f"missing bench {b}")
    # Earnings for stock members (skip pure ETF keys in WEIGHTS)
    stock_syms = [s for s in symbols if s not in WEIGHTS]
    earnings = load_earnings(stock_syms)

    s11 = run_preset("v11", StructureGateConfig.v11(), frames, earnings)
    s12 = run_preset("v12", StructureGateConfig.v12(), frames, earnings)

    delta = {
        "total_return_pp": (s12["structure_gate_total_return"] - s11["structure_gate_total_return"]) * 100,
        "max_drawdown_pp": (s12["structure_gate_max_drawdown"] - s11["structure_gate_max_drawdown"]) * 100,
        "sharpe_delta": s12["structure_gate_sharpe"] - s11["structure_gate_sharpe"],
        "buys_delta": s12["n_buys"] - s11["n_buys"],
    }
    out = {"v11": s11, "v12": s12, "v12_minus_v11": delta}
    (OUT / "summary.json").write_text(json.dumps(out, indent=2, default=float) + "\n", encoding="utf-8")
    print("\n=== DELTA v12 - v11 ===", flush=True)
    print(
        f"return {delta['total_return_pp']:+.2f}pp  maxDD {delta['max_drawdown_pp']:+.2f}pp  "
        f"Sharpe {delta['sharpe_delta']:+.3f}  buys {delta['buys_delta']:+d}",
        flush=True,
    )
    print(f"wrote {OUT / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
