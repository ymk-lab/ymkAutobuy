#!/usr/bin/env python3
"""Compare Regime-CoreSat vs B&H / S12 / CoreSat on QQQ, SOXX, TSLA."""

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
from qresearch.strategy.core_satellite import (
    CoreSatelliteSoftVolStrategy,
    RegimeCoreSatelliteStrategy,
)
from qresearch.strategy.examples import RegimeAwareTrendStrategy
from qresearch.strategy.timing_variants import TimingVariantStrategy

OUT = ROOT / "examples" / "data" / "regime_coresat_compare"
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


def strategies() -> dict[str, Strategy]:
    return {
        "buy_hold": BuyHold(),
        "S12": s12(),
        "CoreSat": CoreSatelliteSoftVolStrategy(
            core_weight=0.70,
            satellite_weight=0.30,
            vol_target=0.15,
            core_scale_floor=0.50,
            soft_vol_cadence="W",
            satellite=s12(),
        ),
        "RegimeCoreSat": RegimeCoreSatelliteStrategy(
            bull_core=0.85,
            bull_sat=0.15,
            base_core=0.70,
            base_sat=0.30,
            bear_core=0.0,
            bear_sat=0.30,
            ma_trend=200,
            ma_soft=100,
            soft_vol_cadence="W",
            satellite=s12(),
        ),
        "RegimeCoreSat_fastSat": RegimeCoreSatelliteStrategy(
            bull_core=0.85,
            bull_sat=0.15,
            base_core=0.70,
            base_sat=0.30,
            bear_core=0.0,
            bear_sat=0.30,
            ma_trend=200,
            ma_soft=100,
            soft_vol_cadence="W",
            satellite=TimingVariantStrategy(
                entry_mode="fast",
                exit_mode="cross",
                entry_fast=5,
                entry_slow=20,
                fast=10,
                slow=40,
            ),
        ),
    }


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
        print(f"\n===== {sym} =====")
        for name, strat in strategies().items():
            sig = strat.generate_signals(data.loc[:end]).astype(float).clip(0, 1)
            book_mix = None
            if hasattr(strat, "last_book_regime") and strat.last_book_regime is not None:
                book_mix = strat.last_book_regime
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
                mix = {}
                if book_mix is not None:
                    bm = book_mix.loc[w0:w1]
                    vc = bm.value_counts(normalize=True)
                    mix = {f"book_{k}": float(vc.get(k, 0.0)) for k in ("bull", "base", "bear")}
                row = {
                    "symbol": sym,
                    "strategy": name,
                    "window": wname,
                    "total_return": ret,
                    "total_pnl_usd": ret * CAPITAL,
                    "sharpe": sharpe,
                    "max_drawdown": dd,
                    "avg_exposure": float(pos.abs().mean()),
                    "n_trades": n_trades,
                    **mix,
                }
                rows.append(row)
                if wname == "primary_2025":
                    print(
                        f"{name:22s} ret={ret:+.2%} sharpe={sharpe:.2f} dd={dd:.2%} "
                        f"exp={float(pos.abs().mean()):.1%} trades={n_trades}"
                        + (
                            f" bull={mix.get('book_bull', 0):.0%} bear={mix.get('book_bear', 0):.0%}"
                            if mix
                            else ""
                        )
                    )

    out = pd.DataFrame(rows)
    # vs bh / coresat / s12 within symbol-window
    enriched = []
    for (sym, wname), g in out.groupby(["symbol", "window"]):
        bh = g.loc[g.strategy == "buy_hold"].iloc[0]
        s12r = g.loc[g.strategy == "S12"].iloc[0]
        cs = g.loc[g.strategy == "CoreSat"].iloc[0]
        for _, row in g.iterrows():
            d = row.to_dict()
            d["vs_bh_ret"] = d["total_return"] - float(bh["total_return"])
            d["vs_bh_sharpe"] = d["sharpe"] - float(bh["sharpe"])
            d["vs_bh_dd"] = d["max_drawdown"] - float(bh["max_drawdown"])
            d["vs_s12_ret"] = d["total_return"] - float(s12r["total_return"])
            d["vs_s12_sharpe"] = d["sharpe"] - float(s12r["sharpe"])
            d["vs_s12_dd"] = d["max_drawdown"] - float(s12r["max_drawdown"])
            d["vs_cs_ret"] = d["total_return"] - float(cs["total_return"])
            d["vs_cs_sharpe"] = d["sharpe"] - float(cs["sharpe"])
            d["vs_cs_dd"] = d["max_drawdown"] - float(cs["max_drawdown"])
            enriched.append(d)
    edf = pd.DataFrame(enriched)
    edf.to_csv(OUT / "summary.csv", index=False)

    print("\n===== PRIMARY vs CoreSat / S12 (Regime variants) =====")
    prim = edf[(edf.window == "primary_2025") & (edf.strategy.str.startswith("Regime"))].copy()
    show = prim[
        [
            "symbol",
            "strategy",
            "total_return",
            "sharpe",
            "max_drawdown",
            "vs_cs_ret",
            "vs_cs_sharpe",
            "vs_cs_dd",
            "vs_s12_ret",
            "vs_s12_dd",
            "book_bull",
            "book_bear",
        ]
    ].copy()
    for c in [
        "total_return",
        "max_drawdown",
        "vs_cs_ret",
        "vs_cs_dd",
        "vs_s12_ret",
        "vs_s12_dd",
        "book_bull",
        "book_bear",
    ]:
        show[c] = show[c].map(lambda v: f"{v:.2%}" if pd.notna(v) else "")
    show["sharpe"] = show["sharpe"].map(lambda v: f"{v:.2f}")
    show["vs_cs_sharpe"] = show["vs_cs_sharpe"].map(lambda v: f"{v:+.2f}")
    print(show.to_string(index=False))

    print("\n===== Full primary scoreboard =====")
    full = edf[edf.window == "primary_2025"][
        ["symbol", "strategy", "total_return", "sharpe", "max_drawdown", "avg_exposure", "n_trades"]
    ].copy()
    for c in ["total_return", "max_drawdown", "avg_exposure"]:
        full[c] = full[c].map(lambda v: f"{v:.2%}")
    full["sharpe"] = full["sharpe"].map(lambda v: f"{v:.2f}")
    print(full.to_string(index=False))

    print("\n===== Secondary 2020 scoreboard =====")
    full2 = edf[edf.window == "secondary_2020"][
        ["symbol", "strategy", "total_return", "sharpe", "max_drawdown", "avg_exposure", "n_trades"]
    ].copy()
    for c in ["total_return", "max_drawdown", "avg_exposure"]:
        full2[c] = full2[c].map(lambda v: f"{v:.2%}")
    full2["sharpe"] = full2["sharpe"].map(lambda v: f"{v:.2f}")
    print(full2.to_string(index=False))

    (OUT / "config.json").write_text(
        json.dumps(
            {
                "symbols": list(SYMBOLS),
                "capital_usd": CAPITAL,
                "trade_threshold": THR,
                "costs": "Futu + 3bps",
                "start_mode": "flat_at_window_start",
                "regime_coresat": {
                    "bull": "85/15 when close>MA200 and not high-vol",
                    "base": "70/30",
                    "bear": "0/30 when close<=MA100 (core can flatten)",
                    "soft_vol": "weekly target 15% floor 50% on active core",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nsaved → {OUT}")


if __name__ == "__main__":
    main()
