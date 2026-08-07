#!/usr/bin/env python3
"""QQQ timing-variant grid: earlier exit / earlier entry vs S12 & CoreSat."""

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
from qresearch.strategy.core_satellite import CoreSatelliteSoftVolStrategy
from qresearch.strategy.examples import RegimeAwareTrendStrategy
from qresearch.strategy.timing_variants import TimingVariantStrategy

OUT = ROOT / "examples" / "data" / "qqq_timing_variants"
CAPITAL = 50_000.0
THR = 0.02


class BuyHold(Strategy):
    name = "buy_hold"

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=data.index)


def fetch(start: str, end: str) -> pd.DataFrame:
    raw = yf.download("QQQ", start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [str(c).lower() for c in raw.columns]
    df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def s12(vol_mult: float = 1.35) -> RegimeAwareTrendStrategy:
    return RegimeAwareTrendStrategy(
        fast=10,
        slow=40,
        high_vol_weight=0.0,
        detector=VolatilityRegimeDetector(lookback=20, high_vol_multiplier=vol_mult),
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
        cost_frac = fees.cost_return_on_equity(float(turnover.iloc[i]), eq, float(open_px.iloc[i]))
        r = w * (float(gap_ret.iloc[i]) + float(asset_ret.iloc[i])) - cost_frac
        eq *= 1.0 + r
        equity[i] = eq
    eq_s = pd.Series(equity, index=ohlcv.index)
    n_trades = int((target.diff().fillna(target).abs() > 1e-12).sum())
    return eq_s, target, n_trades


def coresat(sat: Strategy, floor: float = 0.50) -> CoreSatelliteSoftVolStrategy:
    return CoreSatelliteSoftVolStrategy(
        core_weight=0.70,
        satellite_weight=0.30,
        vol_lookback=20,
        vol_target=0.15,
        core_scale_floor=floor,
        soft_vol_cadence="W",
        satellite=sat,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    end = pd.Timestamp.today().normalize()
    qqq = fetch("2019-01-01", (end + pd.Timedelta(days=3)).strftime("%Y-%m-%d"))
    windows = {
        "primary_2025": (pd.Timestamp("2025-01-01"), min(end, qqq.index.max())),
        "secondary_2020": (pd.Timestamp("2020-01-01"), min(end, qqq.index.max())),
    }

    configs: list[tuple[str, str, Strategy]] = [
        ("B0_bh", "buy&hold", BuyHold()),
        ("B1_s12", "S12 baseline", s12()),
        ("B2_coresat", "CoreSat baseline floor50", coresat(s12(), 0.50)),
        # earlier exit on satellite / full book
        ("E1_s12_ma20exit", "S12 entry cross / exit MA20", TimingVariantStrategy(entry_mode="cross", exit_mode="ma_break", exit_ma=20)),
        ("E2_s12_atr", "S12 entry cross / ATR2.5 exit", TimingVariantStrategy(entry_mode="cross", exit_mode="atr", atr_mult=2.5)),
        ("E3_s12_hybrid", "S12 entry cross / MA20|ATR exit", TimingVariantStrategy(entry_mode="cross", exit_mode="hybrid", exit_ma=20, atr_mult=2.5)),
        ("E4_s12_vol125", "S12 vol mult 1.25 (earlier vol exit)", s12(1.25)),
        # earlier entry
        ("N1_pullback", "pullback reclaim MA20 / exit cross", TimingVariantStrategy(entry_mode="pullback", exit_mode="cross", pullback_ma=20)),
        ("N2_fast_entry", "MA5>20 entry / MA40 cross exit", TimingVariantStrategy(entry_mode="fast", exit_mode="cross", entry_fast=5, entry_slow=20)),
        ("N3_pullback_ma20exit", "pullback in / MA20 out", TimingVariantStrategy(entry_mode="pullback", exit_mode="ma_break", exit_ma=20)),
        ("N4_fast_hybrid", "MA5>20 in / MA20|ATR out", TimingVariantStrategy(entry_mode="fast", exit_mode="hybrid", entry_fast=5, entry_slow=20, exit_ma=20, atr_mult=2.5)),
        # CoreSat with better satellite + floor
        ("C1_coresat_ma20sat", "CoreSat + MA20-exit sat", coresat(TimingVariantStrategy(entry_mode="cross", exit_mode="ma_break", exit_ma=20), 0.50)),
        ("C2_coresat_floor40", "CoreSat baseline floor40", coresat(s12(), 0.40)),
        ("C3_coresat_floor30", "CoreSat baseline floor30", coresat(s12(), 0.30)),
        ("C4_coresat_pull_hyb_f40", "CoreSat pullback+hybrid sat floor40", coresat(TimingVariantStrategy(entry_mode="pullback", exit_mode="hybrid", pullback_ma=20, exit_ma=20, atr_mult=2.5), 0.40)),
        ("C5_coresat_fast_hyb_f40", "CoreSat fast+hybrid sat floor40", coresat(TimingVariantStrategy(entry_mode="fast", exit_mode="hybrid", entry_fast=5, entry_slow=20, exit_ma=20, atr_mult=2.5), 0.40)),
    ]

    rows = []
    for cid, note, strat in configs:
        sig = strat.generate_signals(qqq.loc[:end]).astype(float).clip(0, 1)
        for wname, (w0, w1) in windows.items():
            eq, pos, n_trades = simulate_from_flat(qqq.loc[:end], sig, w0, CAPITAL)
            eq = eq.loc[:w1]
            pos = pos.loc[:w1]
            r = eq.pct_change().fillna(0.0)
            ret = float(eq.iloc[-1] / CAPITAL - 1.0)
            sharpe = float(r.mean() / r.std(ddof=0) * np.sqrt(252)) if r.std(ddof=0) > 1e-12 else 0.0
            dd = float((eq / eq.cummax() - 1.0).min())
            rows.append(
                {
                    "id": cid,
                    "note": note,
                    "window": wname,
                    "total_return": ret,
                    "total_pnl_usd": ret * CAPITAL,
                    "sharpe": sharpe,
                    "max_drawdown": dd,
                    "avg_exposure": float(pos.abs().mean()),
                    "n_trades": n_trades,
                    "end_equity_usd": float(eq.iloc[-1]),
                }
            )

    df = pd.DataFrame(rows)
    # vs baselines within window
    out_rows = []
    for wname, g in df.groupby("window"):
        bh = g.loc[g.id == "B0_bh"].iloc[0]
        s12b = g.loc[g.id == "B1_s12"].iloc[0]
        csb = g.loc[g.id == "B2_coresat"].iloc[0]
        for _, row in g.iterrows():
            d = row.to_dict()
            d["vs_bh_ret"] = d["total_return"] - float(bh["total_return"])
            d["vs_bh_sharpe"] = d["sharpe"] - float(bh["sharpe"])
            d["vs_bh_dd"] = d["max_drawdown"] - float(bh["max_drawdown"])  # less negative = better
            d["vs_s12_ret"] = d["total_return"] - float(s12b["total_return"])
            d["vs_s12_sharpe"] = d["sharpe"] - float(s12b["sharpe"])
            d["vs_s12_dd"] = d["max_drawdown"] - float(s12b["max_drawdown"])
            d["vs_cs_ret"] = d["total_return"] - float(csb["total_return"])
            d["vs_cs_sharpe"] = d["sharpe"] - float(csb["sharpe"])
            d["vs_cs_dd"] = d["max_drawdown"] - float(csb["max_drawdown"])
            out_rows.append(d)
    out = pd.DataFrame(out_rows)
    out.to_csv(OUT / "summary.csv", index=False)

    # rankings for primary: prefer lower |dd| then higher sharpe then return
    prim = out[out.window == "primary_2025"].copy()
    prim["dd_abs"] = prim["max_drawdown"].abs()
    by_dd = prim.sort_values(["dd_abs", "sharpe", "total_return"], ascending=[True, False, False])
    by_sh = prim.sort_values(["sharpe", "dd_abs", "total_return"], ascending=[False, True, False])

    print("\n===== PRIMARY 2025: by shallower DD =====")
    show = by_dd[
        ["id", "note", "total_return", "sharpe", "max_drawdown", "avg_exposure", "n_trades", "vs_s12_dd", "vs_cs_dd"]
    ].copy()
    for c in ["total_return", "max_drawdown", "avg_exposure", "vs_s12_dd", "vs_cs_dd"]:
        show[c] = show[c].map(lambda v: f"{v:.2%}")
    show["sharpe"] = show["sharpe"].map(lambda v: f"{v:.2f}")
    print(show.to_string(index=False))

    print("\n===== PRIMARY 2025: by Sharpe =====")
    show2 = by_sh[
        ["id", "note", "total_return", "sharpe", "max_drawdown", "avg_exposure", "n_trades", "vs_s12_sharpe", "vs_cs_sharpe"]
    ].copy()
    for c in ["total_return", "max_drawdown", "avg_exposure"]:
        show2[c] = show2[c].map(lambda v: f"{v:.2%}")
    show2["sharpe"] = show2["sharpe"].map(lambda v: f"{v:.2f}")
    show2["vs_s12_sharpe"] = show2["vs_s12_sharpe"].map(lambda v: f"{v:+.2f}")
    show2["vs_cs_sharpe"] = show2["vs_cs_sharpe"].map(lambda v: f"{v:+.2f}")
    print(show2.to_string(index=False))

    print("\n===== SECONDARY 2020: by Sharpe =====")
    sec = out[out.window == "secondary_2020"].sort_values("sharpe", ascending=False)
    show3 = sec[["id", "note", "total_return", "sharpe", "max_drawdown", "avg_exposure", "n_trades"]].copy()
    for c in ["total_return", "max_drawdown", "avg_exposure"]:
        show3[c] = show3[c].map(lambda v: f"{v:.2%}")
    show3["sharpe"] = show3["sharpe"].map(lambda v: f"{v:.2f}")
    print(show3.to_string(index=False))

    # winners that improve DD vs S12 without killing return too much on primary
    print("\n===== Useful deltas vs S12 (primary) =====")
    useful = prim[prim.id.str.startswith(("E", "N", "C"))].copy()
    useful = useful.sort_values("vs_s12_dd", ascending=False)
    u = useful[["id", "note", "vs_s12_ret", "vs_s12_sharpe", "vs_s12_dd", "total_return", "sharpe", "max_drawdown"]]
    for c in ["vs_s12_ret", "vs_s12_dd", "total_return", "max_drawdown"]:
        u[c] = u[c].map(lambda v: f"{v:+.2%}" if "vs" in c or c == "total_return" or c == "max_drawdown" else f"{v:.2%}")
    # fix formatting
    u = useful[["id", "note", "vs_s12_ret", "vs_s12_sharpe", "vs_s12_dd", "total_return", "sharpe", "max_drawdown"]].copy()
    u["vs_s12_ret"] = u["vs_s12_ret"].map(lambda v: f"{v:+.2%}")
    u["vs_s12_dd"] = u["vs_s12_dd"].map(lambda v: f"{v:+.2%}")  # + means shallower than S12 if S12 more negative... wait
    # max_drawdown is negative; vs_s12_dd = variant_dd - s12_dd; if variant -8% and s12 -10%, vs = +2% => shallower. Good.
    u["vs_s12_sharpe"] = u["vs_s12_sharpe"].map(lambda v: f"{v:+.2f}")
    u["total_return"] = u["total_return"].map(lambda v: f"{v:.2%}")
    u["sharpe"] = u["sharpe"].map(lambda v: f"{v:.2f}")
    u["max_drawdown"] = u["max_drawdown"].map(lambda v: f"{v:.2%}")
    print(u.to_string(index=False))

    (OUT / "config.json").write_text(
        json.dumps(
            {
                "symbol": "QQQ",
                "capital_usd": CAPITAL,
                "trade_threshold": THR,
                "costs": "Futu + 3bps",
                "start_mode": "flat_at_window_start",
                "n_configs": len(configs),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nsaved → {OUT}")


if __name__ == "__main__":
    main()
