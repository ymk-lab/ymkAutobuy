#!/usr/bin/env python3
"""Second Sharpe grid: event rebalance, rolling vol baseline, MA gate, asymmetric confirm."""

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
from qresearch.strategy.core_satellite import (
    BinaryEntryConfirm,
    CoreSatelliteSoftVolStrategy,
    LongMAGate,
)
from qresearch.strategy.examples import RegimeAwareTrendStrategy

OUT = ROOT / "examples" / "data" / "qqq_coresat_sharpe_grid2"
CAPITAL = 50_000.0


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


def make_s12(baseline_mode: str = "expanding", baseline_window: int = 504) -> RegimeAwareTrendStrategy:
    return RegimeAwareTrendStrategy(
        fast=10,
        slow=40,
        high_vol_weight=0.0,
        detector=VolatilityRegimeDetector(
            lookback=20,
            high_vol_multiplier=1.35,
            baseline_mode=baseline_mode,
            baseline_window=baseline_window,
        ),
    )


def window_stats(res, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    e = res.equity.loc[start:end]
    p = res.positions.reindex(e.index).fillna(0.0)
    r = e.pct_change().fillna(0.0)
    dd = float((e / e.cummax() - 1.0).min())
    mu, sd = float(r.mean()), float(r.std(ddof=0))
    ret = float(e.iloc[-1] / e.iloc[0] - 1.0)
    return {
        "total_return": ret,
        "total_pnl_usd": ret * CAPITAL,
        "max_drawdown": dd,
        "sharpe": float((mu / sd) * np.sqrt(252)) if sd > 1e-12 else 0.0,
        "avg_exposure": float(p.abs().mean()),
        "n_trades": int((p.diff().fillna(p).abs() > 1e-12).sum()),
    }


def build_book(
    *,
    baseline_mode: str = "expanding",
    ma_gate: int | None = None,
    entry_confirm: int = 0,
    exit_confirm: int = 0,
) -> CoreSatelliteSoftVolStrategy:
    sat: Strategy = make_s12(baseline_mode=baseline_mode)
    if ma_gate is not None:
        sat = LongMAGate(base=sat, ma_window=ma_gate)
    if entry_confirm != 0 or exit_confirm != 0:
        sat = BinaryEntryConfirm(
            base=sat,
            entry_confirm_days=entry_confirm,
            exit_confirm_days=exit_confirm,
        )
    return CoreSatelliteSoftVolStrategy(
        core_weight=0.70,
        satellite_weight=0.30,
        vol_lookback=20,
        vol_target=0.15,
        core_scale_floor=0.50,
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

    # Baseline = prior winner: weekly soft-vol 70/30 vol15 thr2%
    configs = [
        dict(
            id="B1_weekly_base",
            note="weekly softvol baseline",
            baseline="expanding",
            ma=None,
            entry=0,
            exit=0,
            mode="threshold",
            thr=0.02,
        ),
        dict(
            id="T1_event_rebalance",
            note="event: week boundary or sat flip",
            baseline="expanding",
            ma=None,
            entry=0,
            exit=0,
            mode="event",
            thr=0.05,
        ),
        dict(
            id="T2_rolling_vol_2y",
            note="S12 vol baseline rolling 504d",
            baseline="rolling",
            ma=None,
            entry=0,
            exit=0,
            mode="threshold",
            thr=0.02,
        ),
        dict(
            id="T3_ma200_gate",
            note="satellite only if close>SMA200",
            baseline="expanding",
            ma=200,
            entry=0,
            exit=0,
            mode="threshold",
            thr=0.02,
        ),
        dict(
            id="T4_enter2_exit0",
            note="asym confirm enter2 exit0",
            baseline="expanding",
            ma=None,
            entry=2,
            exit=0,
            mode="threshold",
            thr=0.02,
        ),
        dict(
            id="T4_enter0_exit2",
            note="asym confirm enter0 exit2",
            baseline="expanding",
            ma=None,
            entry=0,
            exit=2,
            mode="threshold",
            thr=0.02,
        ),
        dict(
            id="T4_enter2_exit1",
            note="asym confirm enter2 exit1",
            baseline="expanding",
            ma=None,
            entry=2,
            exit=1,
            mode="threshold",
            thr=0.02,
        ),
        dict(
            id="STACK_best_dir",
            note="event + rolling + ma200",
            baseline="rolling",
            ma=200,
            entry=0,
            exit=0,
            mode="event",
            thr=0.05,
        ),
    ]

    refs = {"QQQ_buy_hold": BuyHold(), "S12_full": make_s12()}

    rows = []
    for cfg in configs:
        print(f"\n=== {cfg['id']} | {cfg['note']} ===")
        strat = build_book(
            baseline_mode=cfg["baseline"],
            ma_gate=cfg["ma"],
            entry_confirm=cfg["entry"],
            exit_confirm=cfg["exit"],
        )
        engine = WeightBacktestEngine(
            initial_capital=CAPITAL,
            fees=FutuUsEquityFees(slippage_bps=3.0),
            allow_short=False,
            trade_threshold=cfg["thr"],
            rebalance_mode=cfg["mode"],
        )
        res = engine.run(qqq.loc[:end], strat)
        for wname, (w0, w1) in windows.items():
            s = window_stats(res, w0, w1)
            s.update({**{k: cfg[k] for k in ("id", "note", "baseline", "ma", "entry", "exit", "mode", "thr")}, "window": wname, "config_id": cfg["id"]})
            rows.append(s)
            print(
                f"  {wname}: ret={s['total_return']:+.2%} sharpe={s['sharpe']:.3f} "
                f"dd={s['max_drawdown']:.2%} exp={s['avg_exposure']:.1%} trades={s['n_trades']}"
            )

    for name, strat in refs.items():
        print(f"\n=== REF {name} ===")
        engine = WeightBacktestEngine(
            initial_capital=CAPITAL,
            fees=FutuUsEquityFees(slippage_bps=3.0),
            allow_short=False,
            trade_threshold=0.02,
            rebalance_mode="threshold",
        )
        res = engine.run(qqq.loc[:end], strat)
        for wname, (w0, w1) in windows.items():
            s = window_stats(res, w0, w1)
            s.update(
                {
                    "config_id": name,
                    "id": name,
                    "note": "reference",
                    "baseline": "",
                    "ma": None,
                    "entry": 0,
                    "exit": 0,
                    "mode": "threshold",
                    "thr": 0.02,
                    "window": wname,
                }
            )
            rows.append(s)
            print(
                f"  {wname}: ret={s['total_return']:+.2%} sharpe={s['sharpe']:.3f} "
                f"dd={s['max_drawdown']:.2%} trades={s['n_trades']}"
            )

    rdf = pd.DataFrame(rows)
    rdf.to_csv(OUT / "grid_runs.csv", index=False)
    base = rdf[rdf.config_id == "B1_weekly_base"].set_index("window")
    bh = rdf[rdf.config_id == "QQQ_buy_hold"].set_index("window")
    out = []
    for _, row in rdf.iterrows():
        b = base.loc[row.window]
        h = bh.loc[row.window]
        out.append(
            {
                **row.to_dict(),
                "d_sharpe_vs_base": row.sharpe - b.sharpe,
                "d_ret_vs_base": row.total_return - b.total_return,
                "d_sharpe_vs_bh": row.sharpe - h.sharpe,
            }
        )
    odf = pd.DataFrame(out)
    odf.to_csv(OUT / "grid_vs_baseline.csv", index=False)
    prim = odf[odf.window == "primary_2025"].sort_values("sharpe", ascending=False)
    sec = odf[odf.window == "secondary_2020"].sort_values("sharpe", ascending=False)
    prim.to_csv(OUT / "rank_primary_sharpe.csv", index=False)
    sec.to_csv(OUT / "rank_secondary_sharpe.csv", index=False)

    single_ids = [
        "B1_weekly_base",
        "T1_event_rebalance",
        "T2_rolling_vol_2y",
        "T3_ma200_gate",
        "T4_enter2_exit0",
        "T4_enter0_exit2",
        "T4_enter2_exit1",
    ]
    one = odf[odf.config_id.isin(single_ids) & (odf.window == "primary_2025")].sort_values(
        "d_sharpe_vs_base", ascending=False
    )
    one.to_csv(OUT / "one_factor_primary.csv", index=False)

    (OUT / "config.json").write_text(
        json.dumps(
            {
                "baseline": "weekly soft-vol 70/30 vol15 thr2%",
                "capital_usd": CAPITAL,
                "windows": {k: [str(a.date()), str(b.date())] for k, (a, b) in windows.items()},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n===== ONE-FACTOR ΔSharpe vs weekly baseline (primary) =====")
    show = one[["config_id", "note", "sharpe", "d_sharpe_vs_base", "total_return", "max_drawdown", "n_trades"]].copy()
    show["sharpe"] = show["sharpe"].map(lambda v: f"{v:.3f}")
    show["d_sharpe_vs_base"] = show["d_sharpe_vs_base"].map(lambda v: f"{v:+.3f}")
    show["total_return"] = show["total_return"].map(lambda v: f"{v:.2%}")
    show["max_drawdown"] = show["max_drawdown"].map(lambda v: f"{v:.2%}")
    print(show.to_string(index=False))

    print("\n===== PRIMARY RANK =====")
    show2 = prim[["config_id", "note", "sharpe", "d_sharpe_vs_bh", "total_return", "max_drawdown", "n_trades"]].copy()
    show2["sharpe"] = show2["sharpe"].map(lambda v: f"{v:.3f}")
    show2["d_sharpe_vs_bh"] = show2["d_sharpe_vs_bh"].map(lambda v: f"{v:+.3f}")
    show2["total_return"] = show2["total_return"].map(lambda v: f"{v:.2%}")
    show2["max_drawdown"] = show2["max_drawdown"].map(lambda v: f"{v:.2%}")
    print(show2.to_string(index=False))

    print("\n===== SECONDARY RANK =====")
    show3 = sec[["config_id", "note", "sharpe", "d_sharpe_vs_bh", "total_return", "max_drawdown"]].copy()
    show3["sharpe"] = show3["sharpe"].map(lambda v: f"{v:.3f}")
    show3["d_sharpe_vs_bh"] = show3["d_sharpe_vs_bh"].map(lambda v: f"{v:+.3f}")
    show3["total_return"] = show3["total_return"].map(lambda v: f"{v:.2%}")
    show3["max_drawdown"] = show3["max_drawdown"].map(lambda v: f"{v:.2%}")
    print(show3.to_string(index=False))
    print("saved", OUT)


if __name__ == "__main__":
    main()
