#!/usr/bin/env python3
"""One-factor-at-a-time Sharpe grid for QQQ core-satellite book."""

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
from qresearch.strategy.core_satellite import BinaryEntryConfirm, CoreSatelliteSoftVolStrategy
from qresearch.strategy.examples import RegimeAwareTrendStrategy

OUT = ROOT / "examples" / "data" / "qqq_coresat_sharpe_grid"
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


def s12() -> RegimeAwareTrendStrategy:
    return RegimeAwareTrendStrategy(
        fast=10,
        slow=40,
        high_vol_weight=0.0,
        detector=VolatilityRegimeDetector(lookback=20, high_vol_multiplier=1.35),
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
    core: float,
    sat: float,
    vol_target: float,
    cadence: str,
    confirm_days: int | None,
) -> CoreSatelliteSoftVolStrategy:
    satellite: Strategy = s12()
    if confirm_days is not None:
        satellite = BinaryEntryConfirm(base=satellite, confirm_days=confirm_days)
    return CoreSatelliteSoftVolStrategy(
        core_weight=core,
        satellite_weight=sat,
        vol_lookback=20,
        vol_target=vol_target,
        core_scale_floor=0.50,
        soft_vol_cadence=cadence,
        satellite=satellite,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    end = pd.Timestamp.today().normalize()
    qqq = fetch("2019-01-01", (end + pd.Timedelta(days=3)).strftime("%Y-%m-%d"))
    windows = {
        "primary_2025": (pd.Timestamp("2025-01-01"), min(end, qqq.index.max())),
        "secondary_2020": (pd.Timestamp("2020-01-01"), min(end, qqq.index.max())),
    }

    # One change at a time vs baseline; plus a stacked candidate of the best-looking knobs.
    configs = [
        dict(id="B0_baseline", note="70/30 vol15 daily thr2%", core=0.70, sat=0.30, vol=0.15, cadence="D", confirm=None, thr=0.02),
        dict(id="S1_thr5", note="trade_threshold 5%", core=0.70, sat=0.30, vol=0.15, cadence="D", confirm=None, thr=0.05),
        dict(id="S1_weekly_softvol", note="soft-vol weekly", core=0.70, sat=0.30, vol=0.15, cadence="W", confirm=None, thr=0.02),
        dict(id="S2_vol18", note="vol_target 18%", core=0.70, sat=0.30, vol=0.18, cadence="D", confirm=None, thr=0.02),
        dict(id="S3_confirm2", note="satellite 2-day confirm", core=0.70, sat=0.30, vol=0.15, cadence="D", confirm=2, thr=0.02),
        dict(id="S4_80_20", note="core/sat 80/20", core=0.80, sat=0.20, vol=0.15, cadence="D", confirm=None, thr=0.02),
        # stacked: weekly softvol + vol18 + confirm2 + thr5 + 80/20 (aggressive combine of directions)
        dict(id="STACK_a", note="80/20 vol18 weekly thr5 confirm2", core=0.80, sat=0.20, vol=0.18, cadence="W", confirm=2, thr=0.05),
        # milder stack without changing split
        dict(id="STACK_b", note="70/30 vol18 weekly thr5 confirm2", core=0.70, sat=0.30, vol=0.18, cadence="W", confirm=2, thr=0.05),
    ]

    # references
    refs = {
        "QQQ_buy_hold": BuyHold(),
        "S12_full": s12(),
    }

    rows = []
    for cfg in configs:
        print(f"\n=== {cfg['id']} | {cfg['note']} ===")
        strat = build_book(
            core=cfg["core"],
            sat=cfg["sat"],
            vol_target=cfg["vol"],
            cadence=cfg["cadence"],
            confirm_days=cfg["confirm"],
        )
        engine = WeightBacktestEngine(
            initial_capital=CAPITAL,
            fees=FutuUsEquityFees(slippage_bps=3.0),
            allow_short=False,
            trade_threshold=cfg["thr"],
        )
        res = engine.run(qqq.loc[: end], strat)
        for wname, (w0, w1) in windows.items():
            s = window_stats(res, w0, w1)
            s.update(
                {
                    "config_id": cfg["id"],
                    "note": cfg["note"],
                    "window": wname,
                    "core": cfg["core"],
                    "sat": cfg["sat"],
                    "vol_target": cfg["vol"],
                    "cadence": cfg["cadence"],
                    "confirm_days": cfg["confirm"] or 0,
                    "trade_threshold": cfg["thr"],
                }
            )
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
        )
        res = engine.run(qqq.loc[: end], strat)
        for wname, (w0, w1) in windows.items():
            s = window_stats(res, w0, w1)
            s.update(
                {
                    "config_id": name,
                    "note": "reference",
                    "window": wname,
                    "core": np.nan,
                    "sat": np.nan,
                    "vol_target": np.nan,
                    "cadence": "",
                    "confirm_days": 0,
                    "trade_threshold": 0.02,
                }
            )
            rows.append(s)
            print(
                f"  {wname}: ret={s['total_return']:+.2%} sharpe={s['sharpe']:.3f} "
                f"dd={s['max_drawdown']:.2%} exp={s['avg_exposure']:.1%} trades={s['n_trades']}"
            )

    rdf = pd.DataFrame(rows)
    rdf.to_csv(OUT / "grid_runs.csv", index=False)

    # delta vs baseline within each window
    base = rdf[rdf.config_id == "B0_baseline"].set_index("window")
    out = []
    for _, row in rdf.iterrows():
        b = base.loc[row.window]
        out.append(
            {
                **row.to_dict(),
                "d_sharpe_vs_base": row.sharpe - b.sharpe,
                "d_ret_vs_base": row.total_return - b.total_return,
                "d_dd_vs_base": row.max_drawdown - b.max_drawdown,
                "d_sharpe_vs_bh": row.sharpe
                - float(rdf[(rdf.config_id == "QQQ_buy_hold") & (rdf.window == row.window)].sharpe.iloc[0]),
            }
        )
    odf = pd.DataFrame(out)
    odf.to_csv(OUT / "grid_vs_baseline.csv", index=False)

    # summary tables ranked by primary sharpe
    prim = odf[odf.window == "primary_2025"].sort_values("sharpe", ascending=False)
    sec = odf[odf.window == "secondary_2020"].sort_values("sharpe", ascending=False)
    prim.to_csv(OUT / "rank_primary_sharpe.csv", index=False)
    sec.to_csv(OUT / "rank_secondary_sharpe.csv", index=False)

    # one-factor deltas only
    single = odf[
        odf.config_id.isin(
            ["B0_baseline", "S1_thr5", "S1_weekly_softvol", "S2_vol18", "S3_confirm2", "S4_80_20"]
        )
        & (odf.window == "primary_2025")
    ].sort_values("d_sharpe_vs_base", ascending=False)
    single.to_csv(OUT / "one_factor_primary.csv", index=False)

    (OUT / "config.json").write_text(
        json.dumps(
            {
                "capital_usd": CAPITAL,
                "symbol": "QQQ",
                "method": "one-factor-at-a-time + two stacks",
                "windows": {k: [str(a.date()), str(b.date())] for k, (a, b) in windows.items()},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n===== ONE-FACTOR ΔSharpe (primary 2025) =====")
    show = single[
        ["config_id", "note", "sharpe", "d_sharpe_vs_base", "total_return", "max_drawdown", "n_trades"]
    ].copy()
    show["sharpe"] = show["sharpe"].map(lambda v: f"{v:.3f}")
    show["d_sharpe_vs_base"] = show["d_sharpe_vs_base"].map(lambda v: f"{v:+.3f}")
    show["total_return"] = show["total_return"].map(lambda v: f"{v:.2%}")
    show["max_drawdown"] = show["max_drawdown"].map(lambda v: f"{v:.2%}")
    print(show.to_string(index=False))

    print("\n===== PRIMARY RANK by Sharpe =====")
    show2 = prim[
        ["config_id", "note", "sharpe", "d_sharpe_vs_bh", "total_return", "max_drawdown", "avg_exposure"]
    ].copy()
    for c in ["sharpe", "d_sharpe_vs_bh"]:
        show2[c] = show2[c].map(lambda v: f"{v:+.3f}" if c.startswith("d_") else f"{v:.3f}")
    show2["d_sharpe_vs_bh"] = prim["d_sharpe_vs_bh"].map(lambda v: f"{v:+.3f}")
    show2["total_return"] = show2["total_return"].map(lambda v: f"{v:.2%}")
    show2["max_drawdown"] = show2["max_drawdown"].map(lambda v: f"{v:.2%}")
    show2["avg_exposure"] = show2["avg_exposure"].map(lambda v: f"{v:.1%}")
    print(show2.to_string(index=False))

    print("\n===== SECONDARY RANK by Sharpe =====")
    show3 = sec[
        ["config_id", "note", "sharpe", "d_sharpe_vs_bh", "total_return", "max_drawdown"]
    ].copy()
    show3["sharpe"] = show3["sharpe"].map(lambda v: f"{v:.3f}")
    show3["d_sharpe_vs_bh"] = show3["d_sharpe_vs_bh"].map(lambda v: f"{v:+.3f}")
    show3["total_return"] = show3["total_return"].map(lambda v: f"{v:.2%}")
    show3["max_drawdown"] = show3["max_drawdown"].map(lambda v: f"{v:.2%}")
    print(show3.to_string(index=False))
    print(f"\nsaved → {OUT}")


if __name__ == "__main__":
    main()
