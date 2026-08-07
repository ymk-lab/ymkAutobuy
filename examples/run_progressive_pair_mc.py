#!/usr/bin/env python3
"""C(5,2) progressive-scale pairs × 100 runs, QQQ 10-name, 2025-08→2026-08."""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.backtest.costs import CostModel
from qresearch.backtest.engine import BacktestEngine
from qresearch.data.loader import validate_ohlcv
from qresearch.regime.detector import VolatilityRegimeDetector
from qresearch.strategy.examples import RegimeAwareTrendStrategy
from qresearch.strategy.progressive_scale import (
    MinCombineScale,
    PriceConfirmScale,
    PullbackAddScale,
    PyramidScale,
    RegimeTierScale,
    TimeConfirmScale,
)
from qresearch.strategy.relative_strength import RelativeStrengthEntryFilter

OUT = ROOT / "examples" / "data" / "progressive_pair_mc"
WIN_START = "2025-08-01"
WIN_END = "2026-08-01"
FETCH_START = "2024-01-01"
N_RUNS = 100
N_STOCKS = 10
CAPITAL = 50_000.0
SEED = 20260807
S12 = dict(fast=10, slow=40, vol_lb=20, vol_mult=1.35, rs_win=20, rs_thr=0.05)


def fetch_ohlcv(ticker: str, start: str, end: str) -> pd.DataFrame:
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        raise ValueError(f"empty {ticker}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [str(c).lower() for c in raw.columns]
    df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def build_s12(bench: pd.Series):
    base = RegimeAwareTrendStrategy(
        fast=S12["fast"],
        slow=S12["slow"],
        high_vol_weight=0.0,
        detector=VolatilityRegimeDetector(
            lookback=S12["vol_lb"], high_vol_multiplier=S12["vol_mult"]
        ),
    )
    return RelativeStrengthEntryFilter(
        base=base,
        benchmark_close=bench,
        threshold=S12["rs_thr"],
        window=S12["rs_win"],
    )


LOGIC_BUILDERS = {
    "L1_time": lambda b: TimeConfirmScale(base=b),
    "L2_price": lambda b: PriceConfirmScale(base=b),
    "L3_pullback": lambda b: PullbackAddScale(base=b),
    "L4_regime": lambda b: RegimeTierScale(base=b),
    "L5_pyramid": lambda b: PyramidScale(base=b),
}


def build_pair(name_a: str, name_b: str, bench: pd.Series) -> MinCombineScale:
    # each leg gets its own S12+RS instance (stateless w.r.t. each other)
    a = LOGIC_BUILDERS[name_a](build_s12(bench))
    b = LOGIC_BUILDERS[name_b](build_s12(bench))
    return MinCombineScale(a=a, b=b, name=f"{name_a}+{name_b}")


def monthly_pnl_from_equity(equity: pd.Series, capital_slice: float) -> pd.Series:
    """Scale path to capital_slice and return month-end dollar P&L."""
    if equity.empty or float(equity.iloc[0]) == 0:
        return pd.Series(dtype=float)
    scaled = equity / float(equity.iloc[0]) * capital_slice
    month_end = scaled.resample("ME").last().dropna()
    # include start capital as prior for first month
    prev = pd.Series([capital_slice], index=[month_end.index[0] - pd.offsets.MonthEnd(1)])
    path = pd.concat([prev, month_end])
    pnl = path.diff().dropna()
    pnl.index = pnl.index.to_period("M").astype(str)
    return pnl


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pairs = list(itertools.combinations(LOGIC_BUILDERS.keys(), 2))
    assert len(pairs) == 10

    uni = pd.read_csv(ROOT / "examples" / "data" / "qqq100_6m" / "universe.csv")["symbol"].astype(str).tolist()
    print("fetch QQQ + universe...")
    qqq = fetch_ohlcv("QQQ", FETCH_START, "2026-08-05")
    bench = qqq["close"]
    start_ts, end_ts = pd.Timestamp(WIN_START), pd.Timestamp(WIN_END)

    cache: dict[str, pd.DataFrame] = {}
    for i, t in enumerate(uni):
        try:
            cache[t] = fetch_ohlcv(t, FETCH_START, "2026-08-05")
        except Exception as exc:  # noqa: BLE001
            print(" skip", t, exc)
        if (i + 1) % 25 == 0:
            print(f"  cache {i+1}/{len(uni)} ok={len(cache)}")
    print("cache", len(cache))

    engine = BacktestEngine(
        initial_capital=100_000.0,
        cost_model=CostModel(fee_bps=1.0, slippage_bps=3.0),
        allow_short=False,
    )
    rng = np.random.default_rng(SEED)

    # shared 100 baskets
    schedule = []
    pool = [t for t in uni if t in cache and len(cache[t].loc[:start_ts]) >= 60]
    for run in range(N_RUNS):
        picks = rng.choice(pool, size=min(N_STOCKS, len(pool)), replace=False).tolist()
        schedule.append({"run": run, "picks": picks})

    # QQQ buy&hold monthly reference on 50k
    q_eq = bench.loc[start_ts:end_ts].dropna()
    q_pnl = monthly_pnl_from_equity(q_eq, CAPITAL)
    q_pnl.to_csv(OUT / "qqq_bh_monthly_pnl.csv", header=["pnl_usd"])

    run_rows = []
    monthly_rows = []

    for a, b in pairs:
        pair_name = f"{a}+{b}"
        print(f"\n=== {pair_name} ===")
        for item in schedule:
            per_stock_cap = CAPITAL / len(item["picks"])
            month_books: list[pd.Series] = []
            stock_rets = []
            ok = 0
            for t in item["picks"]:
                px = cache[t]
                px_w = px.loc[:end_ts]
                common = px_w.index.intersection(bench.index)
                px_w = px_w.loc[common]
                if len(px_w.loc[:start_ts]) < 60:
                    continue
                strat = build_pair(a, b, bench)
                res = engine.run(px_w, strat)
                eq = res.equity.loc[start_ts:end_ts]
                if len(eq) < 2:
                    continue
                stock_rets.append(float(eq.iloc[-1] / eq.iloc[0] - 1.0))
                month_books.append(monthly_pnl_from_equity(eq, per_stock_cap))
                ok += 1
            if ok < 5:
                print(f"  run{item['run']} ok={ok} skip")
                continue

            # align months and sum dollar pnl
            months = sorted(set().union(*[set(s.index) for s in month_books]))
            m_pnl = {m: 0.0 for m in months}
            for s in month_books:
                for m, v in s.items():
                    m_pnl[m] += float(v)
            total_pnl = float(sum(m_pnl.values()))
            mean_ret = float(np.mean(stock_rets))
            run_rows.append(
                {
                    "pair": pair_name,
                    "logic_a": a,
                    "logic_b": b,
                    "run": item["run"],
                    "n_names": ok,
                    "tickers": ",".join(item["picks"]),
                    "basket_mean_ret": mean_ret,
                    "portfolio_total_pnl_usd": total_pnl,
                    "portfolio_total_ret": total_pnl / CAPITAL,
                    "qqq_ret": float(q_eq.iloc[-1] / q_eq.iloc[0] - 1.0),
                    "vs_qqq_ret": mean_ret - float(q_eq.iloc[-1] / q_eq.iloc[0] - 1.0),
                    "beat_qqq": int(mean_ret > float(q_eq.iloc[-1] / q_eq.iloc[0] - 1.0)),
                    "positive": int(total_pnl > 0),
                }
            )
            for m, v in m_pnl.items():
                monthly_rows.append(
                    {
                        "pair": pair_name,
                        "run": item["run"],
                        "month": m,
                        "pnl_usd": v,
                        "pnl_pct_on_50k": v / CAPITAL,
                    }
                )
        done = [r for r in run_rows if r["pair"] == pair_name]
        if done:
            print(
                f"  runs={len(done)} avg_pnl=${np.mean([r['portfolio_total_pnl_usd'] for r in done]):+,.0f} "
                f"avg_ret={np.mean([r['basket_mean_ret'] for r in done]):+.2%} "
                f"beat_qqq={np.mean([r['beat_qqq'] for r in done]):.0%}"
            )

    rdf = pd.DataFrame(run_rows)
    mdf = pd.DataFrame(monthly_rows)
    rdf.to_csv(OUT / "pair_runs.csv", index=False)
    mdf.to_csv(OUT / "pair_monthly_pnl.csv", index=False)

    # average monthly pnl across runs per pair
    avg_month = (
        mdf.groupby(["pair", "month"], as_index=False)["pnl_usd"].mean()
        .rename(columns={"pnl_usd": "avg_pnl_usd"})
    )
    avg_month["avg_pnl_pct_on_50k"] = avg_month["avg_pnl_usd"] / CAPITAL
    avg_month.to_csv(OUT / "pair_monthly_pnl_avg.csv", index=False)

    summary = []
    for pair, g in rdf.groupby("pair"):
        mg = avg_month[avg_month.pair == pair]
        summary.append(
            {
                "pair": pair,
                "n_runs": len(g),
                "avg_total_pnl_usd": float(g.portfolio_total_pnl_usd.mean()),
                "med_total_pnl_usd": float(g.portfolio_total_pnl_usd.median()),
                "avg_total_ret": float(g.portfolio_total_ret.mean()),
                "avg_basket_ret": float(g.basket_mean_ret.mean()),
                "qqq_ret": float(g.qqq_ret.iloc[0]),
                "avg_vs_qqq": float(g.vs_qqq_ret.mean()),
                "pct_beat_qqq": float(g.beat_qqq.mean()),
                "pct_runs_pos": float(g.positive.mean()),
                "best_month_avg_pnl": float(mg.avg_pnl_usd.max()) if len(mg) else np.nan,
                "worst_month_avg_pnl": float(mg.avg_pnl_usd.min()) if len(mg) else np.nan,
            }
        )
    sdf = pd.DataFrame(summary).sort_values("avg_total_pnl_usd", ascending=False)
    sdf.to_csv(OUT / "pair_summary.csv", index=False)

    # wide monthly table: pair × month avg pnl
    wide = avg_month.pivot(index="pair", columns="month", values="avg_pnl_usd")
    wide.to_csv(OUT / "pair_monthly_pnl_wide.csv")

    cfg = {
        "window": [WIN_START, WIN_END],
        "n_runs": N_RUNS,
        "n_stocks": N_STOCKS,
        "capital_usd": CAPITAL,
        "seed": SEED,
        "combine": "min(weight_a, weight_b)",
        "base": "S12 + RS entry",
        "logics": list(LOGIC_BUILDERS),
        "n_pairs": len(pairs),
        "pairs": [f"{a}+{b}" for a, b in pairs],
    }
    (OUT / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    print("\n===== PAIR SUMMARY (by avg total PnL on $50k) =====")
    show = sdf[
        [
            "pair",
            "avg_total_pnl_usd",
            "avg_total_ret",
            "avg_vs_qqq",
            "pct_beat_qqq",
            "pct_runs_pos",
            "worst_month_avg_pnl",
        ]
    ].copy()
    show["avg_total_pnl_usd"] = show["avg_total_pnl_usd"].map(lambda v: f"${v:+,.0f}")
    show["worst_month_avg_pnl"] = show["worst_month_avg_pnl"].map(lambda v: f"${v:+,.0f}")
    for c in ["avg_total_ret", "avg_vs_qqq", "pct_beat_qqq", "pct_runs_pos"]:
        show[c] = show[c].map(lambda v: f"{v:.2%}")
    print(show.to_string(index=False))
    print(f"\nQQQ B&H over window: {float(q_eq.iloc[-1]/q_eq.iloc[0]-1):+.2%}")
    print("monthly QQQ pnl:\n", q_pnl.round(2).to_string())
    print(f"saved → {OUT}")


if __name__ == "__main__":
    main()
