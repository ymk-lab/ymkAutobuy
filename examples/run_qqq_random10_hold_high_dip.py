#!/usr/bin/env python3
"""Random 10 QQQ-universe names: HoldHighDipScale vs buy&hold (Futu+3bps)."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.data.loader import validate_ohlcv
from qresearch.strategy.base import Strategy
from qresearch.strategy.hold_high_dip import HoldHighDipScaleStrategy

SEED = 42
START = pd.Timestamp("2025-01-01")
END = pd.Timestamp("2026-08-06")
CAPITAL = 50_000.0
THR = 0.02
OUT = ROOT / "examples" / "data" / "qqq_random10_hold_high_dip"

UNIVERSE = sorted(
    {
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "META",
        "GOOGL",
        "AVGO",
        "TSLA",
        "COST",
        "NFLX",
        "AMD",
        "PEP",
        "ADBE",
        "CSCO",
        "TMUS",
        "LIN",
        "TXN",
        "QCOM",
        "INTU",
        "AMGN",
        "ISRG",
        "CMCSA",
        "AMAT",
        "INTC",
        "HON",
        "BKNG",
        "VRTX",
        "ADP",
        "SBUX",
        "GILD",
        "ADI",
        "REGN",
        "LRCX",
        "MU",
        "PANW",
        "KLAC",
        "SNPS",
        "CDNS",
        "MELI",
        "CRWD",
        "MAR",
        "CTAS",
        "ORLY",
        "CSX",
        "PYPL",
        "ASML",
        "NXPI",
        "PCAR",
        "MRVL",
        "FTNT",
        "ADSK",
        "AEP",
        "MNST",
        "ROST",
        "PAYX",
        "CPRT",
        "KDP",
        "IDXX",
        "CHTR",
        "DXCM",
        "EA",
        "VRSK",
        "FAST",
        "EXC",
        "GEHC",
        "TTD",
        "BKR",
        "XEL",
        "CCEP",
        "ON",
        "WBD",
        "ANSS",
        "DDOG",
        "ZS",
        "TEAM",
        "MDB",
        "TTWO",
        "WDAY",
        "ODFL",
        "FANG",
    }
)


class BuyHold(Strategy):
    name = "buy_hold"

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=data.index)


def fetch(ticker: str, start: str, end: str) -> pd.DataFrame:
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [str(c).lower() for c in raw.columns]
    df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def apply_threshold(desired: pd.Series, thr: float = THR) -> pd.Series:
    executed = np.zeros(len(desired), dtype=float)
    prev = 0.0
    for i, w in enumerate(desired.to_numpy(dtype=float)):
        if prev == 0.0 and w != 0.0:
            prev = w
        elif w == 0.0 and prev != 0.0:
            prev = 0.0
        elif abs(w - prev) >= thr:
            prev = w
        executed[i] = prev
    return pd.Series(executed, index=desired.index)


def simulate(
    ohlcv: pd.DataFrame,
    target: pd.Series,
    capital: float,
    fees: FutuUsEquityFees,
) -> tuple[pd.Series, pd.DataFrame]:
    open_px = ohlcv["open"].astype(float)
    close_px = ohlcv["close"].astype(float)
    equity: list[float] = []
    trades: list[dict] = []
    eq = float(capital)
    pos = 0.0
    for i, dt in enumerate(ohlcv.index):
        w = float(target.iloc[i])
        px = float(open_px.iloc[i])
        traded_today = False
        if abs(w - pos) > 1e-12:
            delta = w - pos
            notional = abs(delta) * eq
            cost = fees.total_cost_usd(notional, px)
            side = "BUY" if delta > 0 else "SELL"
            trades.append(
                {
                    "date": dt.strftime("%Y-%m-%d"),
                    "side": side,
                    "weight_from": round(pos, 4),
                    "weight_to": round(w, 4),
                    "delta": round(delta, 4),
                    "price_open": round(px, 4),
                    "notional_usd": round(notional, 2),
                    "cost_usd": round(cost, 2),
                }
            )
            eq = eq - cost
            pos = w
            traded_today = True
        if i == 0:
            day_ret = pos * (float(close_px.iloc[i]) / px - 1.0)
        else:
            prev_c = float(close_px.iloc[i - 1])
            gap = px / prev_c - 1.0
            intra = float(close_px.iloc[i]) / px - 1.0
            day_ret = pos * (gap + intra)
        eq = eq * (1.0 + day_ret)
        if traded_today:
            trades[-1]["equity_after_usd"] = round(eq, 2)
        equity.append(eq)
    return pd.Series(equity, index=ohlcv.index, name="equity"), pd.DataFrame(trades)


def window_metrics(eq: pd.Series, capital: float, pos: pd.Series) -> dict:
    r = eq.pct_change().fillna(0.0)
    dd = float((eq / eq.cummax() - 1.0).min())
    mu, sd = float(r.mean()), float(r.std(ddof=0))
    ret = float(eq.iloc[-1] / capital - 1.0)
    return {
        "total_return": ret,
        "max_drawdown": dd,
        "sharpe": float((mu / sd) * np.sqrt(252)) if sd > 1e-12 else 0.0,
        "avg_exposure": float(pos.abs().mean()),
        "end_equity": float(eq.iloc[-1]),
    }


def main() -> None:
    random.seed(SEED)
    picks = sorted(random.sample(UNIVERSE, 10))
    fees = FutuUsEquityFees(slippage_bps=3.0)
    OUT.mkdir(parents=True, exist_ok=True)

    warm_start = "2023-01-01"
    end_fetch = (END + pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    qqq = fetch("QQQ", warm_start, end_fetch).loc[:END]

    rows = []
    all_trades = []
    print("PICKS:", picks)

    for sym in picks:
        bars = fetch(sym, warm_start, end_fetch).loc[:END]
        idx = bars.index.intersection(qqq.index)
        bars = bars.loc[idx]
        bench = qqq.loc[idx]
        if len(bars.loc[START:END]) < 40:
            print(f"SKIP {sym}: short window")
            continue

        data = bars.copy()
        data["benchmark_close"] = bench["close"].astype(float)
        signal = HoldHighDipScaleStrategy().generate_signals(data).astype(float)
        desired = signal.shift(1).fillna(0.0).clip(0.0, 1.0)

        win = data.loc[START:END]
        target = apply_threshold(desired.reindex(win.index).fillna(0.0), THR)
        bh_tgt = apply_threshold(pd.Series(1.0, index=win.index), THR)

        eq_s, trades_s = simulate(win, target, CAPITAL, fees)
        eq_b, _ = simulate(win, bh_tgt, CAPITAL, fees)
        ms = window_metrics(eq_s, CAPITAL, target)
        mb = window_metrics(eq_b, CAPITAL, bh_tgt)
        vs = (ms["total_return"] - mb["total_return"]) * 100

        rows.append(
            {
                "symbol": sym,
                "bh_return": mb["total_return"],
                "strategy_return": ms["total_return"],
                "vs_bh_pp": vs,
                "beat_bh": ms["total_return"] > mb["total_return"],
                "max_dd": ms["max_drawdown"],
                "bh_max_dd": mb["max_drawdown"],
                "sharpe": ms["sharpe"],
                "bh_sharpe": mb["sharpe"],
                "avg_exposure": ms["avg_exposure"],
                "n_trades": int(len(trades_s)),
                "total_cost_usd": float(trades_s["cost_usd"].sum()) if len(trades_s) else 0.0,
                "end_equity": ms["end_equity"],
                "end_position": float(target.iloc[-1]),
            }
        )
        print(
            f"{sym}: strat={ms['total_return']:+.1%} bh={mb['total_return']:+.1%} "
            f"vs={vs:+.1f}pp dd={ms['max_drawdown']:.1%} trades={len(trades_s)}"
        )
        if len(trades_s):
            t = trades_s.copy()
            t.insert(0, "symbol", sym)
            t.to_csv(OUT / f"trades_{sym.lower()}.csv", index=False)
            all_trades.append(t)
        eq_s.to_csv(OUT / f"equity_{sym.lower()}.csv", header=True)

    summary = pd.DataFrame(rows).sort_values("vs_bh_pp", ascending=False)
    summary.to_csv(OUT / "summary.csv", index=False)
    if all_trades:
        pd.concat(all_trades, ignore_index=True).to_csv(OUT / "all_trades.csv", index=False)

    cfg = {
        "seed": SEED,
        "picks": picks,
        "strategy": "HoldHighDipScaleStrategy",
        "benchmark": "QQQ",
        "capital_usd": CAPITAL,
        "window": [str(START.date()), str(END.date())],
        "costs": "Futu+3bps thr2% next-bar flat-start",
        "params": {
            "exit_ma": 50,
            "reclaim_ma": 50,
            "exit_confirm": 2,
            "rel_lookback": 20,
            "rel_lag": 0.03,
            "add_step": 0.1,
            "max_dip_weight": 0.5,
        },
    }
    (OUT / "config.json").write_text(json.dumps(cfg, indent=2) + "\n")
    print("\n=== SUMMARY ===")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"\nbeat: {int(summary.beat_bh.sum())}/{len(summary)}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
