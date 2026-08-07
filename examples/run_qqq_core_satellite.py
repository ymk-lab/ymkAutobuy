#!/usr/bin/env python3
"""QQQ core-satellite + soft-vol book vs buy&hold and pure S12 (Futu fees + 3bps slip)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.backtest.weight_engine import WeightBacktestEngine
from qresearch.data.loader import validate_ohlcv
from qresearch.regime.detector import VolatilityRegimeDetector
from qresearch.strategy.base import Strategy
from qresearch.strategy.core_satellite import CoreSatelliteSoftVolStrategy
from qresearch.strategy.examples import RegimeAwareTrendStrategy

OUT = ROOT / "examples" / "data" / "qqq_core_satellite"
CAPITAL = 50_000.0


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


def s12() -> RegimeAwareTrendStrategy:
    return RegimeAwareTrendStrategy(
        fast=10,
        slow=40,
        high_vol_weight=0.0,
        detector=VolatilityRegimeDetector(lookback=20, high_vol_multiplier=1.35),
    )


def window_stats(res, start: pd.Timestamp, end: pd.Timestamp, capital: float) -> dict:
    e = res.equity.loc[start:end]
    p = res.positions.reindex(e.index).fillna(0.0)
    r = e.pct_change().fillna(0.0)
    dd = float((e / e.cummax() - 1.0).min())
    mu, sd = float(r.mean()), float(r.std(ddof=0))
    ret = float(e.iloc[-1] / e.iloc[0] - 1.0)
    return {
        "total_return": ret,
        "total_pnl_usd": ret * capital,
        "max_drawdown": dd,
        "sharpe": float((mu / sd) * np.sqrt(252)) if sd > 1e-12 else 0.0,
        "avg_exposure": float(p.abs().mean()),
        "n_trades": int((p.diff().fillna(p).abs() > 1e-12).sum()),
        "end_equity_usd": float(e.iloc[-1] / e.iloc[0] * capital),
    }


def monthly_pnl(equity: pd.Series, capital: float) -> pd.Series:
    scaled = equity / float(equity.iloc[0]) * capital
    me = scaled.resample("ME").last().dropna()
    prev = pd.Series([capital], index=[me.index[0] - pd.offsets.MonthEnd(1)])
    pnl = pd.concat([prev, me]).diff().dropna()
    pnl.index = pnl.index.to_period("M").astype(str)
    return pnl


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    end = pd.Timestamp.today().normalize()
    qqq = fetch("QQQ", "2019-01-01", (end + pd.Timedelta(days=3)).strftime("%Y-%m-%d"))
    engine = WeightBacktestEngine(
        initial_capital=CAPITAL,
        fees=FutuUsEquityFees(slippage_bps=3.0),
        allow_short=False,
    )

    strategies = {
        "QQQ_buy_hold": BuyHold(),
        "S12_full": s12(),
        "CoreSat_SoftVol": CoreSatelliteSoftVolStrategy(
            core_weight=0.70,
            satellite_weight=0.30,
            vol_lookback=20,
            vol_target=0.15,
            core_scale_floor=0.50,
            satellite=s12(),
        ),
    }

    # run once on full history (warmup included)
    results = {name: engine.run(qqq.loc[:end], strat) for name, strat in strategies.items()}

    windows = {
        "primary_2025_to_now": (pd.Timestamp("2025-01-01"), min(end, qqq.index.max())),
        "secondary_2020_to_now": (pd.Timestamp("2020-01-01"), min(end, qqq.index.max())),
    }

    summary_rows = []
    monthly_rows = []
    for wname, (w0, w1) in windows.items():
        print(f"\n===== {wname}: {w0.date()} → {w1.date()} =====")
        for name, res in results.items():
            s = window_stats(res, w0, w1, CAPITAL)
            s.update({"window": wname, "strategy": name})
            summary_rows.append(s)
            print(
                f"{name:16s} ret={s['total_return']:+.2%} pnl=${s['total_pnl_usd']:+,.0f} "
                f"sharpe={s['sharpe']:.2f} dd={s['max_drawdown']:.2%} exp={s['avg_exposure']:.1%} "
                f"trades={s['n_trades']}"
            )
            eq = res.equity.loc[w0:w1]
            for m, v in monthly_pnl(eq, CAPITAL).items():
                monthly_rows.append(
                    {"window": wname, "strategy": name, "month": m, "pnl_usd": float(v)}
                )

    sdf = pd.DataFrame(summary_rows)
    # vs buy hold within window
    out_rows = []
    for wname, g in sdf.groupby("window"):
        bh = float(g.loc[g.strategy == "QQQ_buy_hold", "total_return"].iloc[0])
        bh_sh = float(g.loc[g.strategy == "QQQ_buy_hold", "sharpe"].iloc[0])
        bh_dd = float(g.loc[g.strategy == "QQQ_buy_hold", "max_drawdown"].iloc[0])
        for _, row in g.iterrows():
            d = row.to_dict()
            d["vs_bh_return"] = d["total_return"] - bh
            d["vs_bh_sharpe"] = d["sharpe"] - bh_sh
            d["vs_bh_dd"] = d["max_drawdown"] - bh_dd
            out_rows.append(d)
    out = pd.DataFrame(out_rows)
    out.to_csv(OUT / "summary.csv", index=False)
    pd.DataFrame(monthly_rows).to_csv(OUT / "monthly_pnl.csv", index=False)

    # equity curves for primary window scaled to 50k
    w0, w1 = windows["primary_2025_to_now"]
    curves = {}
    for name, res in results.items():
        e = res.equity.loc[w0:w1]
        curves[name] = e / e.iloc[0] * CAPITAL
    pd.DataFrame(curves).to_csv(OUT / "equity_primary_usd.csv")

    wide = (
        pd.DataFrame(monthly_rows)
        .query("window == 'primary_2025_to_now'")
        .pivot(index="strategy", columns="month", values="pnl_usd")
    )
    wide.to_csv(OUT / "monthly_pnl_primary_wide.csv")

    cfg = {
        "symbol": "QQQ",
        "capital_usd": CAPITAL,
        "core_weight": 0.70,
        "satellite_weight": 0.30,
        "vol_target": 0.15,
        "vol_lookback": 20,
        "core_scale_floor": 0.50,
        "satellite": "S12_full_no_RS",
        "s12": {"fast": 10, "slow": 40, "vol_lb": 20, "vol_mult": 1.35},
        "costs": "Futu US fixed schedule + 3bps slippage",
        "execution": "next-bar open",
        "windows": {k: [str(a.date()), str(b.date())] for k, (a, b) in windows.items()},
        "adr": ["0001", "0002", "0003"],
    }
    (OUT / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    print("\n===== PRIMARY vs B&H =====")
    prim = out[out.window == "primary_2025_to_now"][
        ["strategy", "total_return", "total_pnl_usd", "sharpe", "max_drawdown", "avg_exposure", "vs_bh_return", "vs_bh_sharpe"]
    ].copy()
    for c in ["total_return", "max_drawdown", "avg_exposure", "vs_bh_return"]:
        prim[c] = prim[c].map(lambda v: f"{v:.2%}")
    prim["total_pnl_usd"] = prim["total_pnl_usd"].map(lambda v: f"${v:+,.0f}")
    prim["sharpe"] = prim["sharpe"].map(lambda v: f"{v:.2f}")
    prim["vs_bh_sharpe"] = prim["vs_bh_sharpe"].map(lambda v: f"{v:+.2f}")
    print(prim.to_string(index=False))
    print("\nMonthly PnL primary ($):")
    print(wide.round(0).astype(int).to_string())
    print(f"\nsaved → {OUT}")


if __name__ == "__main__":
    main()
