#!/usr/bin/env python3
"""Bake-Off on SMH book: Regime Label playbook switch vs controls (ADR-0009 analog)."""

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
from qresearch.strategy.emerging_rs_wave import EmergingRSWaveBook
from qresearch.strategy.regime_playbook import (
    RegimePlaybookConfig,
    simulate_bench_bh,
    simulate_cash,
    simulate_regime_switch,
)
from run_emerging_rs_wave_gates import metrics, simulate_book  # type: ignore
from run_emerging_rs_wave_soxx import UNIVERSE  # type: ignore

METHOD = (sys.argv[1] if len(sys.argv) > 1 else "hierarchy").strip().lower()
OUT = ROOT / "examples" / "data" / (
    "regime_playbook_bakeoff_smh_hierarchy"
    if METHOD == "hierarchy"
    else "regime_playbook_bakeoff_smh"
)
CACHE = ROOT / "examples" / "data" / "emerging_rs_wave_smh" / "cache_ohlcv"
CAPITAL = 50_000.0
START = pd.Timestamp("2025-01-01")
END = pd.Timestamp("2026-08-07")
MIN_BARS = 220
BENCH = "SMH"


def _load(path: Path) -> pd.DataFrame | None:
    if not path.is_file() or path.stat().st_size < 64:
        return None
    raw = pd.read_csv(path, index_col=0, parse_dates=True)
    raw.columns = [str(c).lower() for c in raw.columns]
    try:
        df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
    except ValueError:
        return None
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[~df.index.duplicated(keep="last")].sort_index()


def load_panel() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not CACHE.is_dir():
        raise SystemExit(f"SMH OHLCV cache not found: {CACHE}")
    print("cache:", CACHE)
    smh = _load(CACHE / "SMH.csv")
    if smh is None:
        raise SystemExit("SMH missing")
    frames = {}
    for sym in UNIVERSE:
        if sym == BENCH:
            continue
        df = _load(CACHE / f"{sym}.csv")
        if df is not None and len(df) >= MIN_BARS:
            frames[sym] = df.loc[:END]
    smh = smh.loc[:END]
    idx = smh.index
    closes = pd.DataFrame({s: frames[s]["close"].reindex(idx) for s in frames})
    opens = pd.DataFrame({s: frames[s]["open"].reindex(idx) for s in frames})
    keep = [c for c in closes.columns if closes[c].notna().sum() >= MIN_BARS]
    print(f"usable={len(keep)}")
    return smh, opens[keep], closes[keep]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fees = FutuUsEquityFees(slippage_bps=3.0)
    smh, opens, closes = load_panel()

    print(f"label_method={METHOD} bench={BENCH}")
    sw = simulate_regime_switch(
        opens,
        closes,
        smh["open"],
        smh["close"],
        capital=CAPITAL,
        start=START,
        fees=fees,
        config=RegimePlaybookConfig(label_method=METHOD, bench_symbol=BENCH),
        bench_symbol=BENCH,
    )
    m_sw = metrics(sw.equity, CAPITAL)

    book = EmergingRSWaveBook(gate="G1")
    decision, _ = book.generate_weights(closes, smh["close"])
    win = sw.equity.index
    eq_ers, _tr = simulate_book(
        opens.loc[win],
        closes.loc[win],
        decision.loc[win],
        CAPITAL,
        fees,
    )
    m_ers = metrics(eq_ers, CAPITAL)

    eq_bh = simulate_bench_bh(
        smh["open"], smh["close"], capital=CAPITAL, start=START, fees=fees
    )
    eq_bh = eq_bh.reindex(win).ffill()
    m_bh = metrics(eq_bh, CAPITAL)

    eq_cash = simulate_cash(capital=CAPITAL, index=win)
    m_cash = metrics(eq_cash, CAPITAL)

    rows = [
        {"name": "regime_switch", **m_sw},
        {"name": "pure_ers_g1", **m_ers},
        {"name": "smh_bh", **m_bh},
        {"name": "always_smh", **m_bh},
        {"name": "always_cash", **m_cash},
    ]
    summary = pd.DataFrame(rows)
    summary["vs_smh_pp"] = (summary["total_return"] - m_bh["total_return"]) * 100
    summary["vs_ers_pp"] = (summary["total_return"] - m_ers["total_return"]) * 100

    beat_smh = m_sw["total_return"] > m_bh["total_return"]
    beat_ers = m_sw["total_return"] > m_ers["total_return"]
    passed = bool(beat_smh and beat_ers)

    dist = sw.labels.value_counts(normalize=True).sort_values(ascending=False)

    sw.equity.to_csv(OUT / "equity_regime_switch.csv", header=True)
    eq_ers.to_csv(OUT / "equity_pure_ers_g1.csv", header=True)
    eq_bh.to_csv(OUT / "equity_smh_bh.csv", header=True)
    eq_cash.to_csv(OUT / "equity_cash.csv", header=True)
    sw.labels.to_csv(OUT / "labels.csv", header=True)
    sw.raw_labels.to_csv(OUT / "raw_labels.csv", header=True)
    sw.scores.to_csv(OUT / "scores.csv")
    sw.meta.to_csv(OUT / "label_meta.csv")
    if len(sw.trades):
        sw.trades.to_csv(OUT / "trades_regime_switch.csv", index=False)
    summary.to_csv(OUT / "summary.csv", index=False)

    report = {
        "passed_bakeoff": passed,
        "label_method": METHOD,
        "benchmark": BENCH,
        "universe_n": int(closes.shape[1]),
        "criteria": "regime_switch must beat smh_bh AND pure_ers_g1",
        "beat_smh_bh": beat_smh,
        "beat_pure_ers": beat_ers,
        "regime_switch": m_sw,
        "pure_ers_g1": m_ers,
        "smh_bh": m_bh,
        "always_cash": m_cash,
        "label_distribution": dist.to_dict(),
        "fallback_hint": (
            None
            if passed
            else (
                "On SMH CrowdedTrend book, switch still trails SMH B&H and/or ERS — "
                "confirm CrowdedTrend→SMH mapping / thresholds, or keep SMH as B&H-only sleeve."
            )
        ),
        "window": [str(START.date()), str(win.max().date())],
        "capital_usd": CAPITAL,
    }
    (OUT / "bakeoff.json").write_text(json.dumps(report, indent=2, default=float) + "\n")

    print("=== SMH REGIME PLAYBOOK BAKE-OFF ===")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nLabel mix:")
    print((dist * 100).round(1).astype(str) + "%")
    print(
        f"\nPASS={passed} | switch vs SMH "
        f"{summary.loc[summary.name=='regime_switch','vs_smh_pp'].iloc[0]:+.1f}pp "
        f"| vs ERS {summary.loc[summary.name=='regime_switch','vs_ers_pp'].iloc[0]:+.1f}pp"
    )
    if not passed:
        print("HINT:", report["fallback_hint"])
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
