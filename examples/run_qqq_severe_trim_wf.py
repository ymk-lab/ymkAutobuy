#!/usr/bin/env python3
"""Walk-forward QQQ for SevereTrimFastReentry (beat-BH first, then DD)."""

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

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.data.loader import validate_ohlcv
from qresearch.strategy.base import Strategy
from qresearch.strategy.beat_bench import (
    BeatBenchStrategy,
    SevereTrimFastReentryStrategy,
)
from qresearch.strategy.examples import RegimeAwareTrendStrategy
from qresearch.regime.detector import VolatilityRegimeDetector

OUT = ROOT / "examples" / "data" / "qqq_severe_trim_wf"
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


def simulate_slice(ohlcv: pd.DataFrame, signal_full: pd.Series, start: pd.Timestamp, end: pd.Timestamp):
    """Flat-start at `start` using signals computed on full history."""
    fees = FutuUsEquityFees(slippage_bps=3.0)
    desired = signal_full.shift(1).fillna(0.0).clip(0.0, 1.0)
    idx = ohlcv.index[(ohlcv.index >= start) & (ohlcv.index <= end)]
    if len(idx) < 5:
        return None
    desired = desired.reindex(idx).fillna(0.0)
    bar = ohlcv.loc[idx]
    target = apply_threshold(desired, THR)
    open_px = bar["open"].astype(float)
    close_px = bar["close"].astype(float)
    asset_ret = close_px / open_px - 1.0
    gap_ret = (open_px / close_px.shift(1) - 1.0).fillna(0.0)
    turnover = target.diff().abs().fillna(target.abs())
    eq = float(CAPITAL)
    equity = np.empty(len(bar))
    for i in range(len(bar)):
        w = float(target.iloc[i])
        cost = fees.cost_return_on_equity(float(turnover.iloc[i]), eq, float(open_px.iloc[i]))
        r = w * (float(gap_ret.iloc[i]) + float(asset_ret.iloc[i])) - cost
        eq *= 1.0 + r
        equity[i] = eq
    eq_s = pd.Series(equity, index=bar.index)
    r = eq_s.pct_change().fillna(0.0)
    ret = float(eq_s.iloc[-1] / CAPITAL - 1.0)
    sharpe = float(r.mean() / r.std(ddof=0) * np.sqrt(252)) if r.std(ddof=0) > 1e-12 else 0.0
    dd = float((eq_s / eq_s.cummax() - 1.0).min())
    n_trades = int((target.diff().fillna(target).abs() > 1e-12).sum())
    return {
        "total_return": ret,
        "sharpe": sharpe,
        "max_drawdown": dd,
        "avg_exposure": float(target.abs().mean()),
        "n_trades": n_trades,
        "end_equity": float(eq_s.iloc[-1]),
    }


def param_grid():
    for trim, reentry, confirm, severe in itertools.product(
        (0.30, 0.50, 0.70),
        (20, 50),
        (1, 2),
        (50, 100),
    ):
        yield {
            "trim_weight": trim,
            "reentry_ma": reentry,
            "confirm_days": confirm,
            "severe_ma": severe,
        }


def make_strat(p: dict) -> SevereTrimFastReentryStrategy:
    return SevereTrimFastReentryStrategy(
        exit_ma=200,
        severe_ma=p["severe_ma"],
        reentry_ma=p["reentry_ma"],
        confirm_days=p["confirm_days"],
        trim_weight=p["trim_weight"],
    )


def score_vs_bh(stats: dict, bh_ret: float, bh_dd: float) -> tuple:
    # higher vs_bh_ret better; then shallower dd; then higher ret
    return (
        -(stats["total_return"] - bh_ret),
        abs(stats["max_drawdown"]),
        -stats["total_return"],
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    end = pd.Timestamp.today().normalize()
    qqq = fetch("2017-01-01", (end + pd.Timedelta(days=3)).strftime("%Y-%m-%d"))
    qqq = qqq.loc[:end]

    # ---- locked default vs references on research windows ----
    refs = {
        "buy_hold": BuyHold(),
        "STFR_default": SevereTrimFastReentryStrategy(),  # 50% trim, MA50 reentry, confirm2, severe100
        "BB_severe_trim50": BeatBenchStrategy(mode="severe", severe_ma=100, risk_off_weight=0.50),
        "BB_hysteresis_50": BeatBenchStrategy(mode="hysteresis", ma_exit=200, ma_enter=50),
        "S12": RegimeAwareTrendStrategy(
            fast=10,
            slow=40,
            high_vol_weight=0.0,
            detector=VolatilityRegimeDetector(lookback=20, high_vol_multiplier=1.35),
        ),
    }
    windows = {
        "primary_2025": (pd.Timestamp("2025-01-01"), end),
        "secondary_2020": (pd.Timestamp("2020-01-01"), end),
    }
    lock_rows = []
    sigs = {n: s.generate_signals(qqq).astype(float).clip(0, 1) for n, s in refs.items()}
    print("===== Locked configs =====")
    for wname, (w0, w1) in windows.items():
        bh = simulate_slice(qqq, sigs["buy_hold"], w0, w1)
        assert bh is not None
        print(f"\n{wname}")
        for name, sig in sigs.items():
            st = simulate_slice(qqq, sig, w0, w1)
            assert st is not None
            row = {
                "window": wname,
                "strategy": name,
                **st,
                "vs_bh_ret": st["total_return"] - bh["total_return"],
                "vs_bh_dd": st["max_drawdown"] - bh["max_drawdown"],
                "beats_bh": st["total_return"] > bh["total_return"],
            }
            lock_rows.append(row)
            print(
                f"{name:20s} ret={st['total_return']:+.2%} vsBH={row['vs_bh_ret']:+.2%} "
                f"dd={st['max_drawdown']:.2%} sharpe={st['sharpe']:.2f} exp={st['avg_exposure']:.1%} "
                f"trades={st['n_trades']}"
            )
    pd.DataFrame(lock_rows).to_csv(OUT / "locked_summary.csv", index=False)

    # ---- walk-forward: each calendar year OOS, tune on prior 2y ----
    oos_years = list(range(2021, end.year + 1))
    wf_rows = []
    picks = []
    print("\n===== Walk-forward (train prior 2y → OOS year) =====")
    for year in oos_years:
        oos0 = pd.Timestamp(f"{year}-01-01")
        oos1 = min(pd.Timestamp(f"{year}-12-31"), end)
        if oos0 > end:
            continue
        train1 = oos0 - pd.Timedelta(days=1)
        train0 = pd.Timestamp(f"{year - 2}-01-01")
        if train0 < qqq.index.min():
            train0 = qqq.index.min()

        # BH on train for scoring
        bh_sig = sigs["buy_hold"]
        bh_train = simulate_slice(qqq, bh_sig, train0, train1)
        if bh_train is None:
            continue

        best_p = None
        best_key = None
        train_board = []
        for p in param_grid():
            strat = make_strat(p)
            sig = strat.generate_signals(qqq).astype(float).clip(0, 1)
            st = simulate_slice(qqq, sig, train0, train1)
            if st is None:
                continue
            key = score_vs_bh(st, bh_train["total_return"], bh_train["max_drawdown"])
            train_board.append((key, p, st))
            if best_key is None or key < best_key:
                best_key = key
                best_p = p
        assert best_p is not None

        # OOS evaluate chosen + buy_hold + default
        bh_oos = simulate_slice(qqq, bh_sig, oos0, oos1)
        assert bh_oos is not None
        chosen_sig = make_strat(best_p).generate_signals(qqq).astype(float).clip(0, 1)
        chosen = simulate_slice(qqq, chosen_sig, oos0, oos1)
        default = simulate_slice(qqq, sigs["STFR_default"], oos0, oos1)
        assert chosen is not None and default is not None

        pick = {
            "oos_year": year,
            "train_start": str(train0.date()),
            "train_end": str(train1.date()),
            **{f"pick_{k}": v for k, v in best_p.items()},
            "oos_ret": chosen["total_return"],
            "oos_vs_bh": chosen["total_return"] - bh_oos["total_return"],
            "oos_dd": chosen["max_drawdown"],
            "oos_sharpe": chosen["sharpe"],
            "oos_beats_bh": chosen["total_return"] > bh_oos["total_return"],
            "default_oos_ret": default["total_return"],
            "default_oos_vs_bh": default["total_return"] - bh_oos["total_return"],
            "bh_oos_ret": bh_oos["total_return"],
            "bh_oos_dd": bh_oos["max_drawdown"],
        }
        picks.append(pick)
        wf_rows.append(pick)
        print(
            f"{year}: pick trim={best_p['trim_weight']} reentry={best_p['reentry_ma']} "
            f"confirm={best_p['confirm_days']} severe={best_p['severe_ma']} | "
            f"OOS ret={chosen['total_return']:+.2%} vsBH={pick['oos_vs_bh']:+.2%} "
            f"dd={chosen['max_drawdown']:.2%} | default vsBH={pick['default_oos_vs_bh']:+.2%} | "
            f"BH={bh_oos['total_return']:+.2%}"
        )

    pdf = pd.DataFrame(picks)
    pdf.to_csv(OUT / "walkforward_picks.csv", index=False)

    if len(pdf):
        print("\n===== WF aggregate (chosen params) =====")
        print(
            f"years={len(pdf)} beat_bh={int(pdf.oos_beats_bh.sum())}/{len(pdf)} "
            f"avg_vs_bh={pdf.oos_vs_bh.mean():+.2%} median_vs_bh={pdf.oos_vs_bh.median():+.2%} "
            f"avg_dd={pdf.oos_dd.mean():.2%}"
        )
        print(
            f"default STFR: beat_bh={int((pdf.default_oos_vs_bh > 0).sum())}/{len(pdf)} "
            f"avg_vs_bh={pdf.default_oos_vs_bh.mean():+.2%} median_vs_bh={pdf.default_oos_vs_bh.median():+.2%}"
        )
        # compounded OOS path approx via linking yearly returns from flat each year
        # (conservative; not a continuous book)
        def compound(vs):
            eq = 1.0
            for r in vs:
                eq *= 1.0 + r
            return eq - 1.0

        print(
            f"compound OOS chosen={compound(pdf.oos_ret):+.2%} "
            f"default={compound(pdf.default_oos_ret):+.2%} "
            f"BH={compound(pdf.bh_oos_ret):+.2%}"
        )

    (OUT / "config.json").write_text(
        json.dumps(
            {
                "symbol": "QQQ",
                "priority": ["vs_bh_return", "max_drawdown"],
                "default": {
                    "class": "SevereTrimFastReentryStrategy",
                    "trim_weight": 0.5,
                    "reentry_ma": 50,
                    "confirm_days": 2,
                    "severe_ma": 100,
                    "exit_ma": 200,
                },
                "walkforward": {
                    "oos_years": oos_years,
                    "train": "prior_2y",
                    "grid": {
                        "trim_weight": [0.3, 0.5, 0.7],
                        "reentry_ma": [20, 50],
                        "confirm_days": [1, 2],
                        "severe_ma": [50, 100],
                    },
                },
                "costs": "Futu + 3bps",
                "start_mode": "flat_each_window",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nsaved → {OUT}")


if __name__ == "__main__":
    main()
