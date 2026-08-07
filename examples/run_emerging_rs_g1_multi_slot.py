#!/usr/bin/env python3
"""G1 Emerging RS multi-slot backtest: max 10 names, ≤$5k each, QQQ universe."""

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
from qresearch.strategy.emerging_rs_multi_slot import (
    EmergingRSMultiSlotConfig,
    simulate_multi_slot,
)
from run_emerging_rs_wave_gates import CAPITAL, START, UNIVERSE, metrics  # type: ignore

OUT = ROOT / "examples" / "data" / "emerging_rs_g1_multi_slot"
# Prefer Longbridge cache from prior G1 run; fall back to paper cache.
CACHE_CANDIDATES = [
    ROOT / "examples" / "data" / "emerging_rs_wave_qqq_g1_longbridge" / "cache_ohlcv",
    ROOT / "examples" / "data" / "emerging_rs_g1_paper" / "cache_ohlcv",
    Path("/opt/qresearch/examples/data/emerging_rs_wave_qqq_g1_longbridge/cache_ohlcv"),
    Path("/opt/qresearch/examples/data/emerging_rs_g1_paper/cache_ohlcv"),
]
MIN_BARS = 220
END = pd.Timestamp("2026-08-07")


def _load_ohlcv(path: Path) -> pd.DataFrame | None:
    if not path.is_file() or path.stat().st_size < 64:
        return None
    raw = pd.read_csv(path, index_col=0, parse_dates=True)
    raw.columns = [str(c).lower() for c in raw.columns]
    need = ["open", "high", "low", "close", "volume"]
    if any(c not in raw.columns for c in need):
        return None
    try:
        df = validate_ohlcv(raw[need].dropna())
    except ValueError:
        return None
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[~df.index.duplicated(keep="last")].sort_index()


def load_panel() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    cache = next((p for p in CACHE_CANDIDATES if p.is_dir()), None)
    if cache is None:
        raise SystemExit("No OHLCV cache found. Run Longbridge G1 fetch first.")
    print(f"cache: {cache}")
    qqq = _load_ohlcv(cache / "QQQ.csv")
    if qqq is None:
        raise SystemExit("QQQ cache missing")
    frames: dict[str, pd.DataFrame] = {}
    for sym in UNIVERSE:
        df = _load_ohlcv(cache / f"{sym}.csv")
        if df is not None and len(df) >= MIN_BARS:
            frames[sym] = df.loc[:END]
    qqq = qqq.loc[:END]
    print(f"loaded {len(frames)}/{len(UNIVERSE)} names + QQQ")
    return qqq, frames


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    qqq, frames = load_panel()
    idx = qqq.index
    closes = pd.DataFrame({s: frames[s]["close"].reindex(idx) for s in frames})
    opens = pd.DataFrame({s: frames[s]["open"].reindex(idx) for s in frames})
    keep = [c for c in closes.columns if closes[c].notna().sum() >= MIN_BARS]
    closes = closes[keep]
    opens = opens[keep]

    cfg = EmergingRSMultiSlotConfig(max_names=10, max_notional_usd=5_000.0)
    fees = FutuUsEquityFees(slippage_bps=3.0)
    result = simulate_multi_slot(
        opens,
        closes,
        qqq["close"],
        capital=CAPITAL,
        gate="G1",
        config=cfg,
        fees=fees,
        start=START,
    )

    # QQQ B&H for comparison (same window / costs via share buy)
    win = result.equity.index
    qqq_w = qqq.loc[win]
    bh_cash = CAPITAL
    # buy max shares on first open
    first = win[0]
    q_open0 = float(qqq_w.at[first, "open"])
    q_shares = float(np.floor(bh_cash / q_open0))
    q_notional = q_shares * q_open0
    q_cost = fees.total_cost_usd(q_notional, q_open0)
    bh_cash -= q_notional + q_cost
    bh_eq = bh_cash + q_shares * qqq_w["close"]
    bh_eq.name = "equity"
    bh = metrics(bh_eq, CAPITAL)
    m = metrics(result.equity, CAPITAL)

    result.equity.to_csv(OUT / "equity.csv", header=True)
    result.cash.to_csv(OUT / "cash.csv", header=True)
    result.holdings_count.to_csv(OUT / "n_holdings.csv", header=True)
    bh_eq.to_csv(OUT / "equity_qqq_bh.csv", header=True)
    if len(result.trades):
        result.trades.to_csv(OUT / "trades.csv", index=False)
    if len(result.events):
        result.events.to_csv(OUT / "events.csv", index=False)

    # monthly pnl
    me = result.equity.resample("ME").last()
    prev = CAPITAL
    rows = []
    for dt, eg in me.items():
        eg = float(eg)
        rows.append(
            {
                "month": f"{dt:%Y-%m}",
                "equity_end": round(eg, 2),
                "pnl_usd": round(eg - prev, 2),
                "ret": eg / prev - 1.0,
            }
        )
        prev = eg
    monthly = pd.DataFrame(rows)
    monthly.to_csv(OUT / "monthly_pnl.csv", index=False)

    n_buy = int((result.trades["side"] == "BUY").sum()) if len(result.trades) else 0
    n_sell = int((result.trades["side"] == "SELL").sum()) if len(result.trades) else 0
    max_hold = int(result.holdings_count.max()) if len(result.holdings_count) else 0
    avg_hold = float(result.holdings_count.mean()) if len(result.holdings_count) else 0.0
    cost_total = float(result.trades["cost_usd"].sum()) if len(result.trades) else 0.0

    summary = {
        **m,
        "gate": "G1",
        "max_names": cfg.max_names,
        "max_notional_usd": cfg.max_notional_usd,
        "capital_usd": CAPITAL,
        "window": [str(START.date()), str(win.max().date())],
        "universe_n_used": len(keep),
        "bh_return": bh["total_return"],
        "bh_max_drawdown": bh["max_drawdown"],
        "vs_bh_pp": (m["total_return"] - bh["total_return"]) * 100,
        "beat_bh": bool(m["total_return"] > bh["total_return"]),
        "n_trades": int(len(result.trades)),
        "n_buys": n_buy,
        "n_sells": n_sell,
        "n_events": int(len(result.events)),
        "max_concurrent": max_hold,
        "avg_concurrent": avg_hold,
        "cost_total_usd": cost_total,
        "final_positions": result.final_positions,
        "final_cash": float(result.cash.iloc[-1]) if len(result.cash) else CAPITAL,
        "rules": {
            "entry": "Emerging RS + G1 gate; fill free slots by 20d excess rank",
            "size": "≤$5000 notional / name, integer shares; skip if price>$5000",
            "slots": "max 10; sell frees slot for next candidate until cash exhausted",
            "exit": "weaken half→flat; peakDD≥10% or gate_off→flat",
            "costs": "Futu HK US fixed + 3bps; next-open; flat-start",
        },
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float) + "\n")
    pd.DataFrame(
        [
            {
                k: summary[k]
                for k in (
                    "total_return",
                    "max_drawdown",
                    "sharpe",
                    "end_equity",
                    "bh_return",
                    "vs_bh_pp",
                    "beat_bh",
                    "n_buys",
                    "n_sells",
                    "max_concurrent",
                    "avg_concurrent",
                    "cost_total_usd",
                )
            }
        ]
    ).to_csv(OUT / "summary.csv", index=False)

    print(
        f"G1 multi-slot: ret={m['total_return']:+.1%} dd={m['max_drawdown']:.1%} "
        f"sharpe={m['sharpe']:.2f} end=${m['end_equity']:,.0f}"
    )
    print(f"QQQ_BH: ret={bh['total_return']:+.1%} dd={bh['max_drawdown']:.1%}")
    print(
        f"vs QQQ {summary['vs_bh_pp']:+.1f} pp | buys={n_buy} sells={n_sell} "
        f"max_hold={max_hold} avg_hold={avg_hold:.1f} cost=${cost_total:,.0f}"
    )
    print(f"final positions: {result.final_positions or '(flat)'}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
