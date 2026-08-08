#!/usr/bin/env python3
"""Bake-Off: Regime Label playbook switch vs controls (ADR-0009)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.data.loader import validate_ohlcv
from qresearch.strategy.emerging_rs_wave import EmergingRSWaveBook
from qresearch.strategy.regime_playbook import (
    RegimePlaybookConfig,
    simulate_cash,
    simulate_qqq_bh,
    simulate_regime_switch,
)
from run_emerging_rs_wave_gates import (  # type: ignore
    CAPITAL,
    START,
    UNIVERSE,
    metrics,
    simulate_book,
)

OUT = ROOT / "examples" / "data" / "regime_playbook_bakeoff"
CACHE_CANDIDATES = [
    ROOT / "examples" / "data" / "emerging_rs_wave_qqq_g1_longbridge" / "cache_ohlcv",
    Path("/opt/qresearch/examples/data/emerging_rs_wave_qqq_g1_longbridge/cache_ohlcv"),
]
END = pd.Timestamp("2026-08-07")
MIN_BARS = 220


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
    cache = next((p for p in CACHE_CANDIDATES if p.is_dir()), None)
    if cache is None:
        raise SystemExit("QQQ OHLCV cache not found")
    print("cache:", cache)
    qqq = _load(cache / "QQQ.csv")
    if qqq is None:
        raise SystemExit("QQQ missing")
    frames = {}
    for sym in UNIVERSE:
        df = _load(cache / f"{sym}.csv")
        if df is not None and len(df) >= MIN_BARS:
            frames[sym] = df.loc[:END]
    qqq = qqq.loc[:END]
    idx = qqq.index
    closes = pd.DataFrame({s: frames[s]["close"].reindex(idx) for s in frames})
    opens = pd.DataFrame({s: frames[s]["open"].reindex(idx) for s in frames})
    keep = [c for c in closes.columns if closes[c].notna().sum() >= MIN_BARS]
    print(f"usable={len(keep)}")
    return qqq, opens[keep], closes[keep]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fees = FutuUsEquityFees(slippage_bps=3.0)
    qqq, opens, closes = load_panel()

    # 1) Regime switch
    sw = simulate_regime_switch(
        opens,
        closes,
        qqq["open"],
        qqq["close"],
        capital=CAPITAL,
        start=START,
        fees=fees,
        config=RegimePlaybookConfig(),
    )
    m_sw = metrics(sw.equity, CAPITAL)

    # 2) Pure ERS G1
    book = EmergingRSWaveBook(gate="G1")
    decision, _ = book.generate_weights(closes, qqq["close"])
    win = sw.equity.index
    eq_ers, tr_ers = simulate_book(
        opens.loc[win],
        closes.loc[win],
        decision.loc[win],
        CAPITAL,
        fees,
    )
    m_ers = metrics(eq_ers, CAPITAL)

    # 3) QQQ B&H
    eq_bh = simulate_qqq_bh(qqq["open"], qqq["close"], capital=CAPITAL, start=START, fees=fees)
    eq_bh = eq_bh.reindex(win).ffill()
    m_bh = metrics(eq_bh, CAPITAL)

    # 4) Always CrowdedTrend = always QQQ (same as B&H here)
    m_always_qqq = dict(m_bh)
    m_always_qqq["note"] = "same_as_qqq_bh"

    # 5) Always Cash
    eq_cash = simulate_cash(capital=CAPITAL, index=win)
    m_cash = metrics(eq_cash, CAPITAL)

    rows = [
        {"name": "regime_switch", **m_sw},
        {"name": "pure_ers_g1", **m_ers},
        {"name": "qqq_bh", **m_bh},
        {"name": "always_qqq", **{k: m_always_qqq[k] for k in ("total_return", "max_drawdown", "sharpe", "end_equity")}},
        {"name": "always_cash", **m_cash},
    ]
    summary = pd.DataFrame(rows)
    summary["vs_qqq_pp"] = (summary["total_return"] - m_bh["total_return"]) * 100
    summary["vs_ers_pp"] = (summary["total_return"] - m_ers["total_return"]) * 100

    beat_qqq = m_sw["total_return"] > m_bh["total_return"]
    beat_ers = m_sw["total_return"] > m_ers["total_return"]
    passed = bool(beat_qqq and beat_ers)

    # Label distribution
    dist = sw.labels.value_counts(normalize=True).sort_values(ascending=False)

    sw.equity.to_csv(OUT / "equity_regime_switch.csv", header=True)
    eq_ers.to_csv(OUT / "equity_pure_ers_g1.csv", header=True)
    eq_bh.to_csv(OUT / "equity_qqq_bh.csv", header=True)
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
        "criteria": "regime_switch must beat qqq_bh AND pure_ers_g1",
        "beat_qqq_bh": beat_qqq,
        "beat_pure_ers": beat_ers,
        "regime_switch": m_sw,
        "pure_ers_g1": m_ers,
        "qqq_bh": m_bh,
        "always_cash": m_cash,
        "label_distribution": dist.to_dict(),
        "fallback_hint": (
            None
            if passed
            else "Scorecard underperformed pass gate — consider switching classifier to risk-first hierarchy (ADR-0009 option A)."
        ),
        "window": [str(START.date()), str(win.max().date())],
        "capital_usd": CAPITAL,
    }
    (OUT / "bakeoff.json").write_text(json.dumps(report, indent=2, default=float) + "\n")

    print("=== REGIME PLAYBOOK BAKE-OFF ===")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nLabel mix:")
    print((dist * 100).round(1).astype(str) + "%")
    print(
        f"\nPASS={passed} | switch vs QQQ {summary.loc[summary.name=='regime_switch','vs_qqq_pp'].iloc[0]:+.1f}pp "
        f"| vs ERS {summary.loc[summary.name=='regime_switch','vs_ers_pp'].iloc[0]:+.1f}pp"
    )
    if not passed:
        print("HINT:", report["fallback_hint"])
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
