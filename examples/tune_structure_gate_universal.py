#!/usr/bin/env python3
"""~50-trial Structure Gate tune for best universal config across all books.

Same evaluation window as bakeoff. Results are in-window exploratory —
not a locked out-of-sample claim.

Score (higher better):
  1000 * soft_pass_count
  + 100 * hard_pass_count
  + median(vs_bh_pp)
  + 0.5 * min(vs_bh_pp)
  + 0.25 * mean(vs_bh_pp)
  + 0.10 * mean(vs_ers_pp)
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.strategy.emerging_rs_wave import EmergingRSWaveBook
from qresearch.strategy.regime_playbook import simulate_bench_bh
from qresearch.strategy.structure_gate import (
    StructureGateConfig,
    crowded_mask,
    leader_vs_bench_trail,
    sticky_regime,
    strong_leader_weights,
    structure_features,
    trailing_ers_excess,
    thrust_mask,
)
from run_emerging_rs_wave_gates import CAPITAL, START, metrics, simulate_book  # type: ignore
from run_structure_gate_bakeoff import BOOKS, SOFT_MAX_GAP_PP, load_panel  # type: ignore

OUT = ROOT / "examples" / "data" / "structure_gate_tune_v7"
N_TRIALS = 50
ALL_BOOKS = ["QQQ", "SMH", "SOXX", "SPY", "DIA", "IWM", "XLF", "XLK", "XBI", "XLE"]

TUNE_KEYS = [
    "stock_led_min_trail",
    "index_lean_max_trail",
    "sticky_enter_trail",
    "sticky_enter_confirm",
    "sticky_exit_trail",
    "sticky_exit_confirm",
    "sticky_breadth_max",
    "sticky_breadth_trail",
    "thrust_ret5_min",
    "thrust_ret10_min",
    "thrust_bounce20_min",
    "thrust_ret20_min",
    "mild_defense_dd",
    "mild_defense_ret20",
    "harsh_defense_dd",
    "harsh_defense_ret20",
    "top3_conc_min",
    "crowded_overlap_min",
    "strong_share_min",
    "ers_lag_trigger",
]


def soft_hard(sw: float, bh: float, ers: float) -> dict:
    better = max(bh, ers)
    worse = min(bh, ers)
    gap_pp = (better - sw) * 100
    return {
        "soft_pass": bool(sw > worse and gap_pp <= SOFT_MAX_GAP_PP),
        "hard_pass": bool(sw > bh and sw > ers),
        "gap_vs_better_pp": gap_pp,
    }


def make_trials(rng: np.random.Generator) -> list[dict]:
    base = StructureGateConfig()
    trials: list[dict] = []

    def pack(**over) -> dict:
        d = {k: getattr(base, k) for k in TUNE_KEYS}
        d.update(over)
        return d

    trials.append(pack())
    trials += [
        pack(sticky_enter_trail=-0.07, sticky_enter_confirm=3),
        pack(sticky_enter_trail=-0.03, sticky_enter_confirm=1),
        pack(sticky_exit_confirm=3, sticky_exit_trail=-0.01),
        pack(sticky_exit_confirm=8, sticky_exit_trail=-0.03),
        pack(thrust_ret5_min=0.03, thrust_ret10_min=0.05, thrust_bounce20_min=0.06, thrust_ret20_min=0.08),
        pack(thrust_ret5_min=0.06, thrust_ret10_min=0.10, thrust_bounce20_min=0.12, thrust_ret20_min=0.14),
        pack(stock_led_min_trail=0.03, index_lean_max_trail=-0.04),
        pack(stock_led_min_trail=0.015, index_lean_max_trail=-0.02),
        pack(mild_defense_dd=0.10, mild_defense_ret20=-0.04),
        pack(mild_defense_dd=0.06, mild_defense_ret20=-0.02),
        pack(harsh_defense_dd=0.15, harsh_defense_ret20=-0.10),
        pack(harsh_defense_dd=0.10, harsh_defense_ret20=-0.06),
        pack(sticky_breadth_max=0.35, sticky_breadth_trail=-0.10),
        pack(ers_lag_trigger=-0.08, top3_conc_min=0.40, crowded_overlap_min=0.45),
        pack(ers_lag_trigger=-0.03, top3_conc_min=0.30, strong_share_min=0.25),
        pack(
            stock_led_min_trail=0.035,
            index_lean_max_trail=-0.02,
            sticky_enter_trail=-0.04,
            sticky_enter_confirm=1,
            thrust_ret5_min=0.03,
            thrust_ret10_min=0.05,
            thrust_bounce20_min=0.06,
        ),
        pack(
            stock_led_min_trail=0.01,
            index_lean_max_trail=-0.05,
            sticky_enter_trail=-0.08,
            sticky_enter_confirm=3,
            thrust_ret20_min=0.14,
            mild_defense_dd=0.10,
        ),
        pack(
            mild_defense_dd=0.06,
            harsh_defense_dd=0.10,
            harsh_defense_ret20=-0.06,
            sticky_exit_confirm=3,
            thrust_ret5_min=0.05,
        ),
        # Less sticky coverage / more cash defense on wild books
        pack(
            sticky_enter_trail=-0.08,
            sticky_enter_confirm=3,
            sticky_exit_confirm=3,
            thrust_ret5_min=0.05,
            thrust_ret10_min=0.09,
            stock_led_min_trail=0.04,
            mild_defense_dd=0.06,
            harsh_defense_dd=0.10,
        ),
    ]
    while len(trials) < N_TRIALS:
        trials.append(
            pack(
                stock_led_min_trail=float(rng.choice([0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04])),
                index_lean_max_trail=float(rng.choice([-0.05, -0.04, -0.03, -0.025, -0.02, -0.015])),
                sticky_enter_trail=float(rng.choice([-0.08, -0.07, -0.06, -0.05, -0.04, -0.03])),
                sticky_enter_confirm=int(rng.choice([1, 2, 3])),
                sticky_exit_trail=float(rng.choice([-0.04, -0.03, -0.02, -0.01, 0.0])),
                sticky_exit_confirm=int(rng.choice([3, 4, 5, 6, 8])),
                sticky_breadth_max=float(rng.choice([0.30, 0.35, 0.40, 0.45, 0.50])),
                sticky_breadth_trail=float(rng.choice([-0.12, -0.10, -0.08, -0.06])),
                thrust_ret5_min=float(rng.choice([0.025, 0.03, 0.04, 0.05, 0.06])),
                thrust_ret10_min=float(rng.choice([0.05, 0.06, 0.07, 0.08, 0.10])),
                thrust_bounce20_min=float(rng.choice([0.05, 0.06, 0.08, 0.10, 0.12])),
                thrust_ret20_min=float(rng.choice([0.07, 0.08, 0.10, 0.12, 0.14])),
                mild_defense_dd=float(rng.choice([0.06, 0.07, 0.08, 0.10, 0.12])),
                mild_defense_ret20=float(rng.choice([-0.05, -0.04, -0.03, -0.02])),
                harsh_defense_dd=float(rng.choice([0.10, 0.12, 0.14, 0.15, 0.18])),
                harsh_defense_ret20=float(rng.choice([-0.12, -0.10, -0.08, -0.06, -0.05])),
                top3_conc_min=float(rng.choice([0.30, 0.35, 0.40])),
                crowded_overlap_min=float(rng.choice([0.35, 0.40, 0.45])),
                strong_share_min=float(rng.choice([0.25, 0.30, 0.35])),
                ers_lag_trigger=float(rng.choice([-0.08, -0.05, -0.03])),
            )
        )
    return trials[:N_TRIALS]


def label_fast(
    feat: pd.DataFrame,
    trail20: pd.Series,
    trail60: pd.Series,
    excess: pd.Series,
    cfg: StructureGateConfig,
) -> pd.Series:
    crowded = crowded_mask(feat, excess, config=cfg)
    sticky = sticky_regime(feat, trail60, config=cfg)
    thrust = thrust_mask(feat, config=cfg)
    stock_led = trail20 >= cfg.stock_led_min_trail
    index_lean = trail20 <= cfg.index_lean_max_trail
    harsh_dd = (feat["dd60"] <= -cfg.harsh_defense_dd).fillna(False)
    harsh_ret = (feat["ret20"] <= cfg.harsh_defense_ret20).fillna(False)
    mild = (
        (feat["above50"] < 0.5)
        | (feat["dd60"] <= -cfg.mild_defense_dd)
        | (feat["ret20"] <= cfg.mild_defense_ret20)
    ).fillna(False)

    sticky_lock = sticky & ~harsh_ret
    if cfg.thrust_force_bench:
        thrust_lock = thrust & ~harsh_ret
        if not cfg.thrust_overrides_dd_harsh:
            thrust_lock = thrust_lock & ~harsh_dd
    else:
        thrust_lock = pd.Series(False, index=feat.index)
    risk_on = ~mild & ~harsh_dd & ~harsh_ret
    outside = ~(sticky_lock | thrust_lock) if cfg.sticky_forbid_stock_sleeves else (~thrust_lock)

    mode = pd.Series("cash", index=feat.index, dtype=object)
    mode = mode.mask(outside & risk_on & ~index_lean, "ers")
    mode = mode.mask(outside & risk_on & stock_led & crowded, "strong")
    mode = mode.mask(outside & risk_on & index_lean, "bench")
    mode = mode.mask(outside & mild & ~harsh_ret, "cash")
    mode = mode.mask(outside & harsh_dd & ~harsh_ret, "cash")
    mode = mode.mask(sticky_lock, "bench")
    mode = mode.mask(thrust_lock, "bench")
    mode = mode.mask(harsh_ret, "cash")
    return mode


def simulate_from_mode(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    bench_open: pd.Series,
    bench_close: pd.Series,
    mode: pd.Series,
    ers_w: pd.DataFrame,
    strong_w: pd.DataFrame,
    *,
    capital: float,
    start: pd.Timestamp,
    fees: FutuUsEquityFees,
) -> pd.Series:
    """Next-open simulator matching structure_gate.simulate_structure_gate."""
    px = closes.astype(float).sort_index()
    op = opens.astype(float).reindex(px.index)
    qo = bench_open.astype(float).reindex(px.index)
    qc = bench_close.astype(float).reindex(px.index)
    mode = mode.reindex(px.index).fillna("cash")
    ers_w = ers_w.reindex(px.index).fillna(0.0)
    strong_w = strong_w.reindex(px.index).fillna(0.0)
    dates = list(px.index)

    cash = float(capital)
    pos_sym: str | None = None
    pos_shares = 0.0
    pos_kind = "cash"
    pending = "cash"
    target_sym: str | None = None
    target_w = 0.0
    equity_rows: list[float] = []
    eq_index: list[pd.Timestamp] = []

    def _active(weights_row: pd.Series) -> tuple[str | None, float]:
        active = weights_row[weights_row.abs() > 1e-12]
        if len(active) == 0:
            return None, 0.0
        return str(active.index[0]), float(active.iloc[0])

    def _mark(dt: pd.Timestamp) -> float:
        if pos_kind == "cash" or pos_shares <= 0 or pos_sym is None:
            return cash
        if pos_kind == "bench":
            return cash + pos_shares * float(qc.at[dt])
        return cash + pos_shares * float(px.at[dt, pos_sym])

    def _sell_all(dt: pd.Timestamp) -> None:
        nonlocal cash, pos_sym, pos_shares, pos_kind
        if pos_sym is None or pos_shares <= 0:
            return
        px_o = float(qo.at[dt]) if pos_kind == "bench" else float(op.at[dt, pos_sym])
        if not np.isfinite(px_o) or px_o <= 0:
            return
        notional = pos_shares * px_o
        cost = float(fees.total_cost_usd(notional, px_o))
        cash += notional - cost
        pos_sym, pos_shares, pos_kind = None, 0.0, "cash"

    def _buy_stock(dt: pd.Timestamp, sym: str, weight: float, kind: str) -> None:
        nonlocal cash, pos_sym, pos_shares, pos_kind
        px_o = float(op.at[dt, sym])
        if not np.isfinite(px_o) or px_o <= 0:
            return
        shares = float(np.floor(cash * abs(weight) / px_o))
        if shares < 1:
            return
        notional = shares * px_o
        cost = float(fees.total_cost_usd(notional, px_o))
        if notional + cost > cash:
            shares = float(np.floor((cash * 0.999) / px_o))
            if shares < 1:
                return
            notional = shares * px_o
            cost = float(fees.total_cost_usd(notional, px_o))
        cash -= notional + cost
        pos_sym, pos_shares, pos_kind = sym, shares, kind

    def _buy_bench(dt: pd.Timestamp) -> None:
        nonlocal cash, pos_sym, pos_shares, pos_kind
        px_o = float(qo.at[dt])
        if not np.isfinite(px_o) or px_o <= 0:
            return
        shares = float(np.floor(cash / px_o))
        if shares < 1:
            return
        notional = shares * px_o
        cost = float(fees.total_cost_usd(notional, px_o))
        if notional + cost > cash:
            shares = float(np.floor((cash * 0.999) / px_o))
            if shares < 1:
                return
            notional = shares * px_o
            cost = float(fees.total_cost_usd(notional, px_o))
        cash -= notional + cost
        pos_sym, pos_shares, pos_kind = "BENCH", shares, "bench"

    for dt in dates:
        if dt >= start:
            if pending == "cash":
                _sell_all(dt)
            elif pending == "bench":
                if pos_kind != "bench":
                    _sell_all(dt)
                if pos_kind == "cash":
                    _buy_bench(dt)
            elif pending in ("ers", "strong"):
                kind = pending
                if pos_kind not in ("cash", kind):
                    _sell_all(dt)
                sym, w = target_sym, target_w
                if sym is None or w <= 0:
                    if pos_kind == kind:
                        _sell_all(dt)
                else:
                    if pos_kind == kind and pos_sym != sym:
                        _sell_all(dt)
                    if pos_kind == "cash":
                        _buy_stock(dt, sym, w, kind)
            eq_index.append(dt)
            equity_rows.append(_mark(dt))

        m = str(mode.at[dt])
        if m == "cash":
            pending, target_sym, target_w = "cash", None, 0.0
        elif m == "bench":
            pending, target_sym, target_w = "bench", "BENCH", 1.0
        elif m == "strong":
            sym, w = _active(strong_w.loc[dt])
            pending, target_sym, target_w = "strong", sym, w
        else:
            sym, w = _active(ers_w.loc[dt])
            pending, target_sym, target_w = "ers", sym, w

        if dt < start:
            cash = float(capital)
            pos_sym, pos_shares, pos_kind = None, 0.0, "cash"

    return pd.Series(equity_rows, index=pd.DatetimeIndex(eq_index), name="equity")


def preload(books: list[str]) -> dict[str, dict]:
    fees = FutuUsEquityFees(slippage_bps=3.0)
    base = StructureGateConfig()
    out: dict[str, dict] = {}
    for book in books:
        print(f"preload {book}...", flush=True)
        t0 = time.time()
        bench, opens, closes, cache = load_panel(book)
        feat = structure_features(bench["close"], closes, config=base)
        excess = trailing_ers_excess(bench["close"], closes, config=base)
        strong_w = strong_leader_weights(closes, bench["close"], config=base)
        trail20 = leader_vs_bench_trail(closes, bench["close"], config=base, leader_weights=strong_w)
        cfg_long = replace(base, leadership_trail_days=base.sticky_trail_days)
        trail60 = leader_vs_bench_trail(closes, bench["close"], config=cfg_long, leader_weights=strong_w)
        ers_w, _ = EmergingRSWaveBook(gate="G1").generate_weights(closes, bench["close"])
        # Baselines on eval window
        mode0 = label_fast(feat, trail20, trail60, excess, base)
        eq0 = simulate_from_mode(
            opens, closes, bench["open"], bench["close"], mode0, ers_w, strong_w,
            capital=CAPITAL, start=START, fees=fees,
        )
        win = eq0.index
        eq_ers, _ = simulate_book(opens.loc[win], closes.loc[win], ers_w.loc[win], CAPITAL, fees)
        eq_bh = simulate_bench_bh(
            bench["open"], bench["close"], capital=CAPITAL, start=START, fees=fees
        ).reindex(win).ffill()
        m_bh = metrics(eq_bh, CAPITAL)
        m_ers = metrics(eq_ers, CAPITAL)
        out[book] = {
            "opens": opens,
            "closes": closes,
            "bench": bench,
            "feat": feat,
            "excess": excess,
            "trail20": trail20,
            "trail60": trail60,
            "ers_w": ers_w,
            "strong_w": strong_w,
            "fees": fees,
            "bh_ret": m_bh["total_return"],
            "ers_ret": m_ers["total_return"],
            "cache": str(cache),
            "baseline_ret": metrics(eq0, CAPITAL)["total_return"],
        }
        print(
            f"  {time.time()-t0:.1f}s bh={m_bh['total_return']:+.1%} "
            f"ers={m_ers['total_return']:+.1%} gate0={out[book]['baseline_ret']:+.1%}",
            flush=True,
        )
    return out


def score_books(book_rows: list[dict]) -> dict:
    df = pd.DataFrame(book_rows)
    soft_n = int(df["soft_pass"].sum())
    hard_n = int(df["hard_pass"].sum())
    vs_bh = df["vs_bh_pp"]
    vs_ers = df["vs_ers_pp"]
    score = (
        1000.0 * soft_n
        + 100.0 * hard_n
        + float(vs_bh.median())
        + 0.5 * float(vs_bh.min())
        + 0.25 * float(vs_bh.mean())
        + 0.10 * float(vs_ers.mean())
    )
    return {
        "score": score,
        "soft_pass_n": soft_n,
        "hard_pass_n": hard_n,
        "median_vs_bh_pp": float(vs_bh.median()),
        "min_vs_bh_pp": float(vs_bh.min()),
        "mean_vs_bh_pp": float(vs_bh.mean()),
        "mean_vs_ers_pp": float(vs_ers.mean()),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    books = [b.strip().upper() for b in sys.argv[1:]] or ALL_BOOKS
    books = [b for b in books if b in BOOKS]
    rng = np.random.default_rng(7)
    trials = make_trials(rng)
    print(f"books={books} trials={len(trials)}", flush=True)
    panels = preload(books)

    results = []
    best = None
    t_all = time.time()
    for i, knobs in enumerate(trials):
        t0 = time.time()
        cfg = StructureGateConfig(**knobs)
        book_rows = []
        for book, p in panels.items():
            mode = label_fast(p["feat"], p["trail20"], p["trail60"], p["excess"], cfg)
            eq = simulate_from_mode(
                p["opens"],
                p["closes"],
                p["bench"]["open"],
                p["bench"]["close"],
                mode,
                p["ers_w"],
                p["strong_w"],
                capital=CAPITAL,
                start=START,
                fees=p["fees"],
            )
            m = metrics(eq, CAPITAL)
            gate = soft_hard(m["total_return"], p["bh_ret"], p["ers_ret"])
            book_rows.append(
                {
                    "book": book,
                    "total_return": m["total_return"],
                    "max_drawdown": m["max_drawdown"],
                    "vs_bh_pp": (m["total_return"] - p["bh_ret"]) * 100,
                    "vs_ers_pp": (m["total_return"] - p["ers_ret"]) * 100,
                    **gate,
                }
            )
        sc = score_books(book_rows)
        row = {
            "trial": i,
            **sc,
            "elapsed_s": time.time() - t0,
            "knobs": knobs,
            "books": book_rows,
        }
        results.append(row)
        if best is None or row["score"] > best["score"]:
            best = row
        print(
            f"[{i:02d}/{len(trials)-1}] score={sc['score']:.1f} "
            f"soft={sc['soft_pass_n']}/{len(books)} hard={sc['hard_pass_n']} "
            f"med={sc['median_vs_bh_pp']:+.1f} min={sc['min_vs_bh_pp']:+.1f} "
            f"({row['elapsed_s']:.1f}s) BEST=#{best['trial']:02d}/{best['score']:.1f}",
            flush=True,
        )

    results_sorted = sorted(results, key=lambda r: r["score"], reverse=True)
    summary = {
        "rule": "structure_gate_v7_universal_tune",
        "n_trials": len(trials),
        "books": books,
        "window": [str(START.date()), "2026-08-07"],
        "score_definition": (
            "1000*soft_n + 100*hard_n + median(vs_bh_pp) + 0.5*min(vs_bh_pp) "
            "+ 0.25*mean(vs_bh_pp) + 0.10*mean(vs_ers_pp)"
        ),
        "soft_max_gap_pp": SOFT_MAX_GAP_PP,
        "note": "In-window exploratory tune; not locked OOS.",
        "baseline_trial": 0,
        "baseline_score": results[0]["score"],
        "baseline_soft_n": results[0]["soft_pass_n"],
        "baseline_hard_n": results[0]["hard_pass_n"],
        "best_trial": best["trial"],
        "best_score": best["score"],
        "best_soft_n": best["soft_pass_n"],
        "best_hard_n": best["hard_pass_n"],
        "best_knobs": best["knobs"],
        "best_books": best["books"],
        "delta_score_vs_baseline": best["score"] - results[0]["score"],
        "top10": [
            {
                "trial": r["trial"],
                "score": r["score"],
                "soft_pass_n": r["soft_pass_n"],
                "hard_pass_n": r["hard_pass_n"],
                "median_vs_bh_pp": r["median_vs_bh_pp"],
                "min_vs_bh_pp": r["min_vs_bh_pp"],
                "knobs": r["knobs"],
            }
            for r in results_sorted[:10]
        ],
        "elapsed_s": time.time() - t_all,
    }
    (OUT / "tune_summary.json").write_text(json.dumps(summary, indent=2, default=float) + "\n")
    pd.DataFrame(
        [
            {
                "trial": r["trial"],
                "score": r["score"],
                "soft_pass_n": r["soft_pass_n"],
                "hard_pass_n": r["hard_pass_n"],
                "median_vs_bh_pp": r["median_vs_bh_pp"],
                "min_vs_bh_pp": r["min_vs_bh_pp"],
                "mean_vs_bh_pp": r["mean_vs_bh_pp"],
            }
            for r in results_sorted
        ]
    ).to_csv(OUT / "leaderboard.csv", index=False)
    (OUT / "all_trials.json").write_text(json.dumps(results_sorted, indent=2, default=float) + "\n")
    (OUT / "best_knobs.json").write_text(json.dumps(best["knobs"], indent=2) + "\n")

    print("\n=== BEST vs BASELINE ===", flush=True)
    print(
        f"baseline: score={results[0]['score']:.1f} soft={results[0]['soft_pass_n']} hard={results[0]['hard_pass_n']}"
    )
    print(
        f"best #{best['trial']}: score={best['score']:.1f} soft={best['soft_pass_n']} hard={best['hard_pass_n']}"
    )
    print("best knobs:", json.dumps(best["knobs"], indent=2))
    print("per book:")
    for b in best["books"]:
        print(
            f"  {b['book']}: ret={b['total_return']*100:+.1f}% vsBH={b['vs_bh_pp']:+.1f} "
            f"vsERS={b['vs_ers_pp']:+.1f} soft={b['soft_pass']} hard={b['hard_pass']}"
        )
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
