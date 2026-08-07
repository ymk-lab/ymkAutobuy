#!/usr/bin/env python3
"""Beat-benchmark-first design compare on QQQ / SOXX / TSLA."""

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
from qresearch.data.loader import validate_ohlcv
from qresearch.regime.detector import VolatilityRegimeDetector
from qresearch.strategy.base import Strategy
from qresearch.strategy.beat_bench import BeatBenchStrategy, OffenseTrimStrategy
from qresearch.strategy.core_satellite import (
    CoreSatelliteSoftVolStrategy,
    RegimeCoreSatelliteStrategy,
)
from qresearch.strategy.examples import RegimeAwareTrendStrategy

OUT = ROOT / "examples" / "data" / "beat_bench_compare"
CAPITAL = 50_000.0
THR = 0.02
SYMBOLS = ("QQQ", "SOXX", "TSLA")


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


def simulate_from_flat(ohlcv, desired_full, start, capital):
    fees = FutuUsEquityFees(slippage_bps=3.0)
    desired = desired_full.shift(1).fillna(0.0).clip(lower=0.0, upper=1.0).loc[start:]
    ohlcv = ohlcv.loc[desired.index]
    target = apply_threshold(desired, THR)
    open_px = ohlcv["open"].astype(float)
    close_px = ohlcv["close"].astype(float)
    asset_ret = close_px / open_px - 1.0
    gap_ret = (open_px / close_px.shift(1) - 1.0).fillna(0.0)
    turnover = target.diff().abs().fillna(target.abs())
    n = len(ohlcv)
    equity = np.empty(n)
    eq = float(capital)
    for i in range(n):
        w = float(target.iloc[i])
        cost = fees.cost_return_on_equity(float(turnover.iloc[i]), eq, float(open_px.iloc[i]))
        r = w * (float(gap_ret.iloc[i]) + float(asset_ret.iloc[i])) - cost
        eq *= 1.0 + r
        equity[i] = eq
    eq_s = pd.Series(equity, index=ohlcv.index)
    n_trades = int((target.diff().fillna(target).abs() > 1e-12).sum())
    return eq_s, target, n_trades


def catalog() -> dict[str, Strategy]:
    return {
        "buy_hold": BuyHold(),
        "legacy_S12": s12(),
        "legacy_CoreSat": CoreSatelliteSoftVolStrategy(
            core_weight=0.70,
            satellite_weight=0.30,
            vol_target=0.15,
            core_scale_floor=0.50,
            soft_vol_cadence="W",
            satellite=s12(),
        ),
        "legacy_RegimeCoreSat": RegimeCoreSatelliteStrategy(satellite=s12()),
        "BB_ma200": BeatBenchStrategy(mode="ma200"),
        "BB_hysteresis_50": BeatBenchStrategy(mode="hysteresis", ma_exit=200, ma_enter=50),
        "BB_hysteresis_100": BeatBenchStrategy(mode="hysteresis", ma_exit=200, ma_enter=100),
        "BB_fast_reentry_50": BeatBenchStrategy(mode="ma200_fast_reentry", reentry_ma=50),
        "BB_dual_confirm2": BeatBenchStrategy(mode="dual_confirm", confirm_days=2, reentry_ma=50),
        "BB_severe": BeatBenchStrategy(mode="severe", severe_ma=100),
        "BB_severe_ma50": BeatBenchStrategy(mode="severe", severe_ma=50),
        "OT_trim70": OffenseTrimStrategy(trim_weight=0.70),
        "OT_trim85": OffenseTrimStrategy(trim_weight=0.85),
        # partial risk-off instead of flat (stay closer to B&H)
        "BB_hyst50_trim30": BeatBenchStrategy(
            mode="hysteresis", ma_exit=200, ma_enter=50, risk_off_weight=0.30
        ),
        "BB_severe_trim50": BeatBenchStrategy(
            mode="severe", severe_ma=100, risk_off_weight=0.50
        ),
    }


def rank_key(row: pd.Series) -> tuple:
    # 1) beat bench return gap  2) shallower DD  3) higher absolute return
    return (
        -float(row["vs_bh_ret"]),
        float(abs(row["max_drawdown"])),
        -float(row["total_return"]),
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    end = pd.Timestamp.today().normalize()
    windows = {
        "primary_2025": pd.Timestamp("2025-01-01"),
        "secondary_2020": pd.Timestamp("2020-01-01"),
    }
    rows = []
    for sym in SYMBOLS:
        data = fetch(sym, "2018-01-01", (end + pd.Timedelta(days=3)).strftime("%Y-%m-%d"))
        w1 = min(end, data.index.max())
        print(f"\n===== {sym} primary =====")
        for name, strat in catalog().items():
            sig = strat.generate_signals(data.loc[:end]).astype(float).clip(0, 1)
            for wname, w0 in windows.items():
                eq, pos, n_trades = simulate_from_flat(data.loc[:end], sig, w0, CAPITAL)
                eq = eq.loc[:w1]
                pos = pos.loc[:w1]
                r = eq.pct_change().fillna(0.0)
                ret = float(eq.iloc[-1] / CAPITAL - 1.0)
                sharpe = (
                    float(r.mean() / r.std(ddof=0) * np.sqrt(252)) if r.std(ddof=0) > 1e-12 else 0.0
                )
                dd = float((eq / eq.cummax() - 1.0).min())
                rows.append(
                    {
                        "symbol": sym,
                        "strategy": name,
                        "window": wname,
                        "total_return": ret,
                        "total_pnl_usd": ret * CAPITAL,
                        "sharpe": sharpe,
                        "max_drawdown": dd,
                        "avg_exposure": float(pos.abs().mean()),
                        "n_trades": n_trades,
                    }
                )

    df = pd.DataFrame(rows)
    out_rows = []
    for (sym, wname), g in df.groupby(["symbol", "window"]):
        bh = float(g.loc[g.strategy == "buy_hold", "total_return"].iloc[0])
        bh_dd = float(g.loc[g.strategy == "buy_hold", "max_drawdown"].iloc[0])
        for _, row in g.iterrows():
            d = row.to_dict()
            d["vs_bh_ret"] = d["total_return"] - bh
            d["vs_bh_dd"] = d["max_drawdown"] - bh_dd
            d["beats_bh"] = d["vs_bh_ret"] > 0
            out_rows.append(d)
    out = pd.DataFrame(out_rows)
    out.to_csv(OUT / "summary.csv", index=False)

    for sym in SYMBOLS:
        prim = out[(out.symbol == sym) & (out.window == "primary_2025")].copy()
        prim = prim.sort_values(
            by=["vs_bh_ret", "max_drawdown", "total_return"],
            ascending=[False, False, False],
        )
        print(f"\n===== {sym} PRIMARY ranked: beat-BH first, then DD =====")
        show = prim[
            [
                "strategy",
                "total_return",
                "vs_bh_ret",
                "beats_bh",
                "max_drawdown",
                "vs_bh_dd",
                "sharpe",
                "avg_exposure",
                "n_trades",
            ]
        ].copy()
        for c in ["total_return", "vs_bh_ret", "max_drawdown", "vs_bh_dd", "avg_exposure"]:
            show[c] = show[c].map(lambda v: f"{v:+.2%}" if "vs" in c or c.endswith("return") or c.endswith("drawdown") or c == "avg_exposure" else f"{v:.2%}")
        # fix avg_exposure sign
        show["avg_exposure"] = prim["avg_exposure"].map(lambda v: f"{v:.1%}")
        show["total_return"] = prim["total_return"].map(lambda v: f"{v:+.2%}")
        show["vs_bh_ret"] = prim["vs_bh_ret"].map(lambda v: f"{v:+.2%}")
        show["max_drawdown"] = prim["max_drawdown"].map(lambda v: f"{v:.2%}")
        show["vs_bh_dd"] = prim["vs_bh_dd"].map(lambda v: f"{v:+.2%}")
        show["sharpe"] = prim["sharpe"].map(lambda v: f"{v:.2f}")
        print(show.to_string(index=False))

    print("\n===== Winners (primary, must beat BH if any) =====")
    for sym in SYMBOLS:
        prim = out[(out.symbol == sym) & (out.window == "primary_2025")].copy()
        beaters = prim[prim.beats_bh & (prim.strategy != "buy_hold")]
        if len(beaters):
            # among beaters, shallowest DD then highest vs_bh
            win = beaters.sort_values(
                ["max_drawdown", "vs_bh_ret"], ascending=[False, False]
            ).iloc[0]
            print(
                f"{sym}: {win.strategy} ret={win.total_return:+.2%} vsBH={win.vs_bh_ret:+.2%} "
                f"dd={win.max_drawdown:.2%} (beats BH, best DD among beaters)"
            )
        else:
            best = prim.sort_values("vs_bh_ret", ascending=False)
            best = best[best.strategy != "buy_hold"].iloc[0]
            print(
                f"{sym}: NONE beat BH | closest {best.strategy} "
                f"ret={best.total_return:+.2%} vsBH={best.vs_bh_ret:+.2%} dd={best.max_drawdown:.2%}"
            )

    print("\n===== Secondary 2020: beat-BH first =====")
    for sym in SYMBOLS:
        sec = out[(out.symbol == sym) & (out.window == "secondary_2020")].copy()
        sec = sec.sort_values("vs_bh_ret", ascending=False)
        top = sec.head(5)[["strategy", "total_return", "vs_bh_ret", "max_drawdown", "sharpe"]]
        print(f"\n{sym}:")
        t = top.copy()
        t["total_return"] = t["total_return"].map(lambda v: f"{v:+.2%}")
        t["vs_bh_ret"] = t["vs_bh_ret"].map(lambda v: f"{v:+.2%}")
        t["max_drawdown"] = t["max_drawdown"].map(lambda v: f"{v:.2%}")
        t["sharpe"] = t["sharpe"].map(lambda v: f"{v:.2f}")
        print(t.to_string(index=False))

    (OUT / "config.json").write_text(
        json.dumps(
            {
                "priority": ["vs_bh_return", "max_drawdown"],
                "symbols": list(SYMBOLS),
                "capital_usd": CAPITAL,
                "costs": "Futu + 3bps",
                "start_mode": "flat_at_window_start",
                "adr": "0005",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nsaved → {OUT}")


if __name__ == "__main__":
    main()
