#!/usr/bin/env python3
"""Structure Gate v10: cross QQQ / SPY / SMH book bakeoff.

Design
------
- Regime thermometer: SPY (mild / harsh / sticky / thrust / …)
- Stock sleeve universe: union(QQQ members ∪ SMH/SOXX semi members)
- Bench sleeve: best of {SPY, QQQ, SMH} by 20d return (next-open)
- Knobs: StructureGateConfig.v10() (== v8 thresholds)

Compares against single-book v8 on QQQ / SPY / SMH over the same window.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.data.loader import validate_ohlcv
from qresearch.strategy.regime_playbook import simulate_bench_bh
from qresearch.strategy.structure_gate import (
    StructureGateConfig,
    simulate_structure_gate,
    simulate_structure_gate_cross,
)
from run_emerging_rs_wave_gates import UNIVERSE as QQQ_UNIVERSE, metrics  # type: ignore
from run_emerging_rs_wave_soxx import UNIVERSE as SEMI_UNIVERSE  # type: ignore
from run_structure_gate_bakeoff import soft_pass  # type: ignore

OUT = ROOT / "examples" / "data" / "structure_gate_v10_cross"
CAPITAL = 50_000.0
MIN_BARS = 220
ETFS = ["SPY", "QQQ", "SMH"]

CACHE_DIRS = [
    ROOT / "examples/data/structure_gate_v8_paper/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_qqq_g1_longbridge/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_smh/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_soxx/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_spy/cache_ohlcv",
]


def _load_symbol(sym: str) -> pd.DataFrame | None:
    for cache in CACHE_DIRS:
        path = cache / f"{sym}.csv"
        if not path.is_file():
            continue
        try:
            raw = pd.read_csv(path, index_col=0, parse_dates=True)
            raw.columns = [str(c).lower() for c in raw.columns]
            df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            df = df[~df.index.duplicated(keep="last")].sort_index()
            if len(df) >= MIN_BARS:
                return df
        except Exception:
            continue
    return None


def load_panel(symbols: list[str]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for i, s in enumerate(symbols, 1):
        df = _load_symbol(s)
        if df is not None:
            frames[s] = df
        if i == 1 or i % 50 == 0 or i == len(symbols):
            print(f"load [{i}/{len(symbols)}] ok={len(frames)} last={s}", flush=True)
    return frames


def align_stock_panel(
    frames: dict[str, pd.DataFrame], members: list[str], calendar: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.DataFrame]:
    opens = pd.DataFrame({s: frames[s]["open"].reindex(calendar) for s in members if s in frames})
    closes = pd.DataFrame({s: frames[s]["close"].reindex(calendar) for s in members if s in frames})
    keep = [c for c in closes.columns if closes[c].notna().sum() >= MIN_BARS]
    return opens[keep], closes[keep]


def run_single_book(
    book: str,
    frames: dict[str, pd.DataFrame],
    members: list[str],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict:
    if book not in frames:
        raise SystemExit(f"missing bench {book}")
    bdf = frames[book].loc[:end]
    cal = bdf.index
    opens, closes = align_stock_panel(frames, members, cal)
    cfg = StructureGateConfig.v8()
    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    sim = simulate_structure_gate(
        opens,
        closes,
        bdf["open"],
        bdf["close"],
        capital=CAPITAL,
        start=start,
        fees=fees,
        config=cfg,
        bench_volume=bdf["volume"] if "volume" in bdf.columns else None,
    )
    eq = sim.equity
    bh = simulate_bench_bh(
        bdf["open"], bdf["close"], capital=CAPITAL, start=start, fees=fees
    ).reindex(eq.index).ffill()
    m_sg = metrics(eq, CAPITAL)
    m_bh = metrics(bh, CAPITAL)
    return {
        "name": f"v8_{book}",
        "kind": "single_book",
        "book": book,
        "n_members": len(closes.columns),
        "structure_gate": m_sg,
        "bench_bh": m_bh,
        "vs_bh_pp": (m_sg["total_return"] - m_bh["total_return"]) * 100,
        "mode_distribution": sim.mode.value_counts(normalize=True).to_dict(),
        "n_trades": int(len(sim.trades)),
        "equity": eq,
        "trades": sim.trades,
        "mode": sim.mode,
    }


def run_v10(
    frames: dict[str, pd.DataFrame],
    members: list[str],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict:
    for e in ETFS:
        if e not in frames:
            raise SystemExit(f"missing ETF {e}")
    spy = frames["SPY"].loc[:end]
    cal = spy.index
    opens, closes = align_stock_panel(frames, members, cal)
    etf_o = pd.DataFrame({e: frames[e]["open"].reindex(cal) for e in ETFS})
    etf_c = pd.DataFrame({e: frames[e]["close"].reindex(cal) for e in ETFS})
    cfg = StructureGateConfig.v10()
    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    sim = simulate_structure_gate_cross(
        opens,
        closes,
        etf_o,
        etf_c,
        regime_etf="SPY",
        capital=CAPITAL,
        start=start,
        fees=fees,
        config=cfg,
        etf_momentum_lookback=20,
    )
    eq = sim.equity
    bh = simulate_bench_bh(
        spy["open"], spy["close"], capital=CAPITAL, start=start, fees=fees
    ).reindex(eq.index).ffill()
    m_sg = metrics(eq, CAPITAL)
    m_bh = metrics(bh, CAPITAL)
    # bench ETF mix on bench days
    bench_days = sim.meta["bench_etf"].replace("", pd.NA).dropna()
    bench_mix = bench_days.value_counts(normalize=True).to_dict() if len(bench_days) else {}
    stock_trades = sim.trades
    if len(stock_trades):
        buys = stock_trades[stock_trades["side"] == "BUY"]
        sleeve = buys["kind"].value_counts().to_dict() if "kind" in buys.columns else {}
        top_syms = buys["symbol"].value_counts().head(12).to_dict()
    else:
        sleeve, top_syms = {}, {}
    return {
        "name": "v10_cross",
        "kind": "cross_book",
        "regime_etf": "SPY",
        "etf_sleeve": ETFS,
        "n_members": len(closes.columns),
        "structure_gate": m_sg,
        "bench_bh_spy": m_bh,
        "vs_spy_bh_pp": (m_sg["total_return"] - m_bh["total_return"]) * 100,
        "mode_distribution": sim.mode.value_counts(normalize=True).to_dict(),
        "bench_etf_mix": bench_mix,
        "buy_sleeve_counts": sleeve,
        "top_buy_symbols": top_syms,
        "n_trades": int(len(sim.trades)),
        "equity": eq,
        "trades": sim.trades,
        "mode": sim.mode,
        "meta": sim.meta,
    }


def main() -> int:
    start = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2025-01-01")
    end = pd.Timestamp(sys.argv[2] if len(sys.argv) > 2 else "2026-08-07")
    OUT.mkdir(parents=True, exist_ok=True)

    qqq_m = [s for s in QQQ_UNIVERSE if s not in ETFS]
    semi_m = [s for s in SEMI_UNIVERSE if s not in ETFS]
    union = sorted(set(qqq_m) | set(semi_m))
    want = sorted(set(ETFS) | set(union))
    print(f"window {start.date()}→{end.date()} union_members={len(union)} etfs={ETFS}")
    frames = load_panel(want)
    for e in ETFS:
        if e not in frames:
            raise SystemExit(f"ETF {e} not in cache — refetch required")

    results = []
    print("\n=== single-book v8 baselines ===", flush=True)
    spy_members: list[str] = []
    uf = ROOT / "examples/data/emerging_rs_wave_spy/universe.txt"
    if uf.is_file():
        spy_members = [
            ln.strip().upper()
            for ln in uf.read_text().splitlines()
            if ln.strip() and not ln.startswith("#") and ln.strip().upper() != "SPY"
        ]
        missing = [s for s in spy_members if s not in frames]
        if missing:
            print(f"loading extra SPY-universe names: {len(missing)}", flush=True)
            frames.update(load_panel(missing))

    for book, members in (
        ("QQQ", qqq_m),
        ("SPY", spy_members or union),
        ("SMH", semi_m),
    ):
        try:
            r = run_single_book(book, frames, members, start=start, end=end)
        except SystemExit as exc:
            print(f"skip {book}: {exc}")
            continue
        results.append(r)
        print(
            f"{r['name']:10} n={r['n_members']:3d} SG={r['structure_gate']['total_return']*100:7.2f}% "
            f"BH={r['bench_bh']['total_return']*100:6.2f}% vsBH={r['vs_bh_pp']:+6.1f}pp "
            f"maxDD={r['structure_gate']['max_drawdown']*100:6.2f}% trades={r['n_trades']}",
            flush=True,
        )
        r["equity"].to_csv(OUT / f"equity_{r['name']}.csv", header=["equity"])

    print("\n=== v10 cross ===", flush=True)
    v10 = run_v10(frames, union, start=start, end=end)
    results.append(v10)
    print(
        f"{v10['name']:10} n={v10['n_members']:3d} SG={v10['structure_gate']['total_return']*100:7.2f}% "
        f"SPY_BH={v10['bench_bh_spy']['total_return']*100:6.2f}% vsBH={v10['vs_spy_bh_pp']:+6.1f}pp "
        f"maxDD={v10['structure_gate']['max_drawdown']*100:6.2f}% trades={v10['n_trades']}",
        flush=True,
    )
    print("mode", {k: f"{v*100:.1f}%" for k, v in v10["mode_distribution"].items()})
    print("bench_etf_mix", {k: f"{v*100:.1f}%" for k, v in v10["bench_etf_mix"].items()})
    print("top_buys", v10["top_buy_symbols"])

    v10["equity"].to_csv(OUT / "equity_v10_cross.csv", header=["equity"])
    v10["mode"].to_csv(OUT / "modes_v10.csv", header=["mode"])
    if len(v10["trades"]):
        v10["trades"].to_csv(OUT / "trades_v10.csv", index=False)
    v10["meta"][["mode", "bench_etf", "best_etf", "sticky", "thrust", "mild"]].to_csv(
        OUT / "meta_v10.csv"
    )

    # soft vs SPY BH and best single-book SG
    singles = [r for r in results if r["kind"] == "single_book"]
    best_single = max(singles, key=lambda r: r["structure_gate"]["total_return"]) if singles else None
    gate = soft_pass(
        v10["structure_gate"]["total_return"],
        v10["bench_bh_spy"]["total_return"],
        best_single["structure_gate"]["total_return"] if best_single else v10["bench_bh_spy"]["total_return"],
    )

    summary = {
        "ok": True,
        "preset": "v10_cross",
        "start": str(start.date()),
        "end": str(end.date()),
        "capital": CAPITAL,
        "fees": "futu_us+slippage",
        "design": {
            "regime_etf": "SPY",
            "stock_universe": "union(QQQ, SMH/SOXX semi)",
            "bench_sleeve": "best of SPY/QQQ/SMH by 20d return",
            "knobs": "StructureGateConfig.v10() (== v8 thresholds)",
        },
        "v10": {
            "total_return": v10["structure_gate"]["total_return"],
            "max_drawdown": v10["structure_gate"]["max_drawdown"],
            "sharpe": v10["structure_gate"]["sharpe"],
            "end_equity": v10["structure_gate"]["end_equity"],
            "vs_spy_bh_pp": v10["vs_spy_bh_pp"],
            "mode_distribution": v10["mode_distribution"],
            "bench_etf_mix": v10["bench_etf_mix"],
            "n_members": v10["n_members"],
            "n_trades": v10["n_trades"],
            "top_buy_symbols": v10["top_buy_symbols"],
        },
        "baselines": [
            {
                "name": r["name"],
                "total_return": r["structure_gate"]["total_return"],
                "bh_total_return": r["bench_bh"]["total_return"],
                "vs_bh_pp": r["vs_bh_pp"],
                "max_drawdown": r["structure_gate"]["max_drawdown"],
                "n_members": r["n_members"],
            }
            for r in singles
        ],
        "soft_vs_spy_and_best_single": gate,
        "best_single_book": best_single["name"] if best_single else None,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float) + "\n")
    print("\nsummary →", OUT / "summary.json")
    print(
        f"v10 soft={gate.get('soft_pass')} hard_beat_both={gate.get('hard_pass_beat_both')} "
        f"best_single={summary['best_single_book']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
