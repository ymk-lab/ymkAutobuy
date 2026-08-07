#!/usr/bin/env python3
"""All C(100,2) pairwise equal-weight blends of the a priori 100 on QQQ."""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Load tournament module (register name for dataclasses)
_mod_path = ROOT / "examples" / "run_qqq_100_tournament.py"
_spec = importlib.util.spec_from_file_location("qqq_100_tournament", _mod_path)
t100 = importlib.util.module_from_spec(_spec)
sys.modules["qqq_100_tournament"] = t100
assert _spec.loader is not None
_spec.loader.exec_module(t100)

from qresearch.backtest.futu_costs import FutuUsEquityFees

OUT = ROOT / "examples" / "data" / "qqq_100_pairwise"
CAPITAL = t100.CAPITAL
THR = t100.THR
W0, W1 = t100.W0, t100.W1


def simulate_fast(open_px, close_px, signal_on_bars, capital=CAPITAL, thr=THR):
    desired = np.empty_like(signal_on_bars)
    desired[0] = 0.0
    desired[1:] = signal_on_bars[:-1]
    desired = np.clip(desired, 0.0, 1.0)

    target = np.zeros_like(desired)
    prev = 0.0
    for i, w in enumerate(desired):
        if prev == 0.0 and w != 0.0:
            prev = float(w)
        elif w == 0.0 and prev != 0.0:
            prev = 0.0
        elif abs(w - prev) >= thr:
            prev = float(w)
        target[i] = prev

    asset_ret = close_px / open_px - 1.0
    gap = np.empty_like(open_px)
    gap[0] = 0.0
    gap[1:] = open_px[1:] / close_px[:-1] - 1.0
    turn = np.empty_like(target)
    turn[0] = abs(target[0])
    turn[1:] = np.abs(np.diff(target))

    fees = FutuUsEquityFees(slippage_bps=3.0)
    eq = float(capital)
    peak = eq
    max_dd = 0.0
    rets = np.empty_like(target)
    n_trades = 0
    prev_t = 0.0
    for i in range(len(target)):
        w = float(target[i])
        if abs(w - prev_t) > 1e-12:
            n_trades += 1
            prev_t = w
        cost = fees.cost_return_on_equity(float(turn[i]), eq, float(open_px[i]))
        r = w * (float(gap[i]) + float(asset_ret[i])) - cost
        eq *= 1.0 + r
        rets[i] = r
        if eq > peak:
            peak = eq
        dd = eq / peak - 1.0
        if dd < max_dd:
            max_dd = dd
    mu, sd = float(rets.mean()), float(rets.std(ddof=0))
    sharpe = (mu / sd) * np.sqrt(252) if sd > 1e-12 else 0.0
    return eq / capital - 1.0, sharpe, max_dd, float(np.mean(np.abs(target))), n_trades, eq


def main() -> None:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    df = t100.fetch_qqq()
    catalog = t100.build_catalog()
    assert len(catalog) == 100

    print("Building 100 base signals...")
    sigs = []
    meta = []
    for sp, fn, kwargs in catalog:
        s = fn(df, **kwargs).astype(float).clip(0, 1)
        sigs.append(s.reindex(df.index).fillna(0.0).to_numpy(dtype=float))
        meta.append(sp)

    mask = (df.index >= W0) & (df.index <= W1)
    pos = np.where(mask)[0]
    open_px = df["open"].astype(float).to_numpy()[pos]
    close_px = df["close"].astype(float).to_numpy()[pos]
    sig_win = [s[pos] for s in sigs]

    bh_ret, *_ = simulate_fast(open_px, close_px, sig_win[0])
    print(f"B&H ret={bh_ret:+.2%}")

    pairs = list(combinations(range(100), 2))
    print(f"Pairs: {len(pairs)} equal-weight 50/50")

    rows = []
    n_beat = 0
    for k, (i, j) in enumerate(pairs):
        blend = 0.5 * sig_win[i] + 0.5 * sig_win[j]
        ret, sh, dd, exp, ntr, end_eq = simulate_fast(open_px, close_px, blend)
        vs = ret - bh_ret
        beat = bool(vs > 1e-12)
        n_beat += int(beat)
        rows.append(
            {
                "id_a": meta[i].id,
                "id_b": meta[j].id,
                "family_a": meta[i].family,
                "family_b": meta[j].family,
                "params_a": meta[i].params,
                "params_b": meta[j].params,
                "logic_a": meta[i].logic,
                "logic_b": meta[j].logic,
                "total_return": ret,
                "vs_bh_ret": vs,
                "beats_bh": beat,
                "max_drawdown": dd,
                "sharpe": sh,
                "avg_exposure": exp,
                "n_trades": ntr,
                "end_equity_usd": end_eq,
            }
        )
        if (k + 1) % 500 == 0:
            print(f"  ... {k+1}/{len(pairs)} beat_so_far={n_beat}")

    out = pd.DataFrame(rows)
    out = out.sort_values(
        ["vs_bh_ret", "max_drawdown", "total_return"], ascending=[False, False, False]
    ).reset_index(drop=True)
    out.insert(0, "rank", np.arange(1, len(out) + 1))
    out.to_csv(OUT / "pairwise_results.csv", index=False)

    winners = out[out["beats_bh"]]
    print("\n===== PAIRWISE CONTEST =====")
    print(f"Window {W0.date()} → {W1.date()} | ${CAPITAL:,.0f} | blend 50/50")
    print(f"Pairs={len(out)} | Beat B&H={len(winners)} | {time.time()-t0:.1f}s")
    print(f"B&H={bh_ret:+.2%}")

    show = out.head(20).copy()
    for c in ["total_return", "vs_bh_ret", "max_drawdown"]:
        show[c] = show[c].map(lambda v: f"{v:+.2%}" if c != "max_drawdown" else f"{v:.2%}")
    show["sharpe"] = show["sharpe"].map(lambda v: f"{v:.2f}")
    print("\n===== TOP 20 pairs =====")
    print(
        show[
            [
                "rank",
                "id_a",
                "id_b",
                "family_a",
                "family_b",
                "params_a",
                "params_b",
                "total_return",
                "vs_bh_ret",
                "beats_bh",
                "max_drawdown",
                "sharpe",
                "n_trades",
            ]
        ].to_string(index=False)
    )

    if len(winners):
        print(f"\n===== BEATERS ({len(winners)}) — showing up to 40 =====")
        w = winners.head(40).copy()
        for c in ["total_return", "vs_bh_ret", "max_drawdown"]:
            w[c] = w[c].map(lambda v: f"{v:+.2%}" if c != "max_drawdown" else f"{v:.2%}")
        w["sharpe"] = w["sharpe"].map(lambda v: f"{v:.2f}")
        print(
            w[
                [
                    "rank",
                    "id_a",
                    "id_b",
                    "params_a",
                    "params_b",
                    "total_return",
                    "vs_bh_ret",
                    "max_drawdown",
                    "sharpe",
                    "n_trades",
                ]
            ].to_string(index=False)
        )
        # which singles appear most in winning pairs
        cnt = pd.concat([winners["id_a"], winners["id_b"]]).value_counts().head(15)
        print("\nMost frequent members among beating pairs:")
        print(cnt.to_string())
    else:
        print("\nNo pair beat B&H with 50/50 blend.")

    (OUT / "config.json").write_text(
        json.dumps(
            {
                "symbol": "QQQ",
                "capital_usd": CAPITAL,
                "window": [str(W0.date()), str(W1.date())],
                "n_base": 100,
                "combine": "equal_weight_0.5_0.5",
                "n_pairs": len(out),
                "n_beat_bh": int(len(winners)),
                "bh_return": bh_ret,
                "costs": "Futu + 3bps; thr 2%; next-bar; flat start",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nsaved → {OUT}")


if __name__ == "__main__":
    main()
