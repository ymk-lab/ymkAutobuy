#!/usr/bin/env python3
"""Structure Gate v13 vs v11 blend bakeoff + light 10-knob tune.

v13 = v11 capital split (SPY 40 / QQQ 30 / SMH 30) + mode hysteresis
      + risk-override pierce (harsh / held-stock 1d crash).

Usage:
  python examples/run_structure_gate_v13_vs_v11.py
  python examples/run_structure_gate_v13_vs_v11.py --tune 40
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.strategy.regime_playbook import simulate_bench_bh
from qresearch.strategy.structure_gate import (
    V11_BOOK_WEIGHTS,
    StructureGateConfig,
    blend_structure_gate_books,
)
from run_emerging_rs_wave_gates import metrics  # type: ignore
from run_structure_gate_bakeoff import soft_pass  # type: ignore
from run_structure_gate_v11_blend import (  # type: ignore
    CAPITAL,
    WEIGHTS,
    load_many,
    book_members,
    run_book,
)

OUT = ROOT / "examples" / "data" / "structure_gate_v13_vs_v11"

WINDOWS = [
    (pd.Timestamp("2023-01-01"), pd.Timestamp("2024-01-01")),
    (pd.Timestamp("2025-08-07"), pd.Timestamp("2026-08-07")),
]

# 10 knobs tuned for v13 (defaults = StructureGateConfig.v13())
TUNE_KEYS = [
    "mode_enter_trail",
    "mode_exit_trail",
    "mode_switch_cooldown_days",
    "risk_override_stock_1d",
    "mild_defense_dd",
    "mild_defense_ret20",
    "harsh_defense_dd",
    "harsh_defense_ret20",
    "stock_led_min_trail",
    "sma50_hysteresis",
]

TUNE_SPACE: dict[str, list] = {
    "mode_enter_trail": [0.015, 0.020, 0.025, 0.030, 0.035],
    "mode_exit_trail": [-0.005, -0.010, -0.015, -0.020, -0.025],
    "mode_switch_cooldown_days": [0, 1, 2, 3],
    "risk_override_stock_1d": [0.06, 0.08, 0.10, 0.12],
    "mild_defense_dd": [0.05, 0.06, 0.08],
    "mild_defense_ret20": [-0.03, -0.04, -0.05],
    "harsh_defense_dd": [0.15, 0.18, 0.20],
    "harsh_defense_ret20": [-0.10, -0.12, -0.15],
    "stock_led_min_trail": [0.020, 0.025, 0.030],
    "sma50_hysteresis": [0.0, 0.005, 0.010],
}


def run_blend(
    frames: dict[str, pd.DataFrame],
    cfg: StructureGateConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    label: str,
) -> dict:
    book_sims = {}
    sleeve_rows = []
    for book, w in WEIGHTS.items():
        sleeve_cap = CAPITAL * w
        sim, bh, n_mem = run_book(
            book, frames, sleeve_capital=sleeve_cap, start=start, end=end, cfg=cfg
        )
        book_sims[book] = sim
        m = metrics(sim.equity, sleeve_cap)
        mb = metrics(bh, sleeve_cap)
        blocked = 0.0
        pierce = 0.0
        crash = 0.0
        if sim.meta is not None and len(sim.meta):
            if "mode_switch_blocked" in sim.meta.columns:
                blocked = float(sim.meta["mode_switch_blocked"].fillna(0).mean())
            if "risk_override_pierce" in sim.meta.columns:
                pierce = float(sim.meta["risk_override_pierce"].fillna(0).mean())
            if "stock_crash_override" in sim.meta.columns:
                crash = float(sim.meta["stock_crash_override"].fillna(0).mean())
        sleeve_rows.append(
            {
                "book": book,
                "weight": w,
                "n_members": n_mem,
                "total_return": m["total_return"],
                "max_drawdown": m["max_drawdown"],
                "sharpe": m["sharpe"],
                "bh_total_return": mb["total_return"],
                "mode_distribution": sim.mode.value_counts(normalize=True).to_dict(),
                "n_trades": int(len(sim.trades)),
                "mode_switch_blocked_share": blocked,
                "risk_override_pierce_share": pierce,
                "stock_crash_override_share": crash,
            }
        )

    blended, panel = blend_structure_gate_books(book_sims, WEIGHTS, capital=CAPITAL)
    blended = blended.loc[start:end].dropna()
    panel = panel.reindex(blended.index).ffill()
    m_b = metrics(blended, CAPITAL)

    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    spy = frames["SPY"]
    eq_bh = simulate_bench_bh(
        spy["open"], spy["close"], capital=CAPITAL, start=start, fees=fees
    ).reindex(blended.index).ffill()
    m_bh = metrics(eq_bh, CAPITAL)

    etf_eq = []
    for book, w in WEIGHTS.items():
        bdf = frames[book]
        etf_eq.append(
            simulate_bench_bh(
                bdf["open"], bdf["close"], capital=CAPITAL * w, start=start, fees=fees
            )
        )
    static = pd.concat(etf_eq, axis=1).ffill().sum(axis=1).reindex(blended.index).ffill()
    m_static = metrics(static, CAPITAL)
    gate = soft_pass(m_b["total_return"], m_bh["total_return"], m_static["total_return"])

    modes = pd.DataFrame({b: book_sims[b].mode for b in WEIGHTS}).reindex(blended.index).ffill()
    disagree = float((modes.nunique(axis=1) > 1).mean()) if len(modes) else float("nan")
    n_trades = int(sum(r["n_trades"] for r in sleeve_rows))

    tag = f"{label}_{start.date()}_{end.date()}"
    blended.to_csv(OUT / f"equity_{tag}.csv", header=["equity"])
    panel.to_csv(OUT / f"sleeves_{tag}.csv")

    return {
        "label": label,
        "start": str(start.date()),
        "end": str(end.date()),
        "blend": {
            "total_return": m_b["total_return"],
            "max_drawdown": m_b["max_drawdown"],
            "sharpe": m_b["sharpe"],
            "end_equity": m_b["end_equity"],
            "vs_spy_bh_pp": (m_b["total_return"] - m_bh["total_return"]) * 100,
            "vs_static_etf_blend_pp": (m_b["total_return"] - m_static["total_return"]) * 100,
            "n_trades": n_trades,
            "mode_disagree_share": disagree,
        },
        "spy_bh": m_bh,
        "static_etf_403030": m_static,
        "soft_pass": gate,
        "sleeves": sleeve_rows,
    }


def score_report(rep: dict) -> float:
    """Higher is better. Balances return, DD, dual baselines, trade churn."""
    b = rep["blend"]
    ret = float(b["total_return"])
    dd = float(b["max_drawdown"])
    sharpe = float(b["sharpe"])
    vs_spy = float(b["vs_spy_bh_pp"])
    vs_static = float(b["vs_static_etf_blend_pp"])
    trades = float(b["n_trades"])
    # Prefer beating both baselines; penalize deep DD and hyper-churn.
    score = (
        ret * 100.0
        + vs_spy * 0.35
        + vs_static * 0.55
        + sharpe * 8.0
        + dd * 40.0  # dd negative
        - max(0.0, trades - 80) * 0.08
    )
    if rep["soft_pass"].get("hard_pass_beat_both"):
        score += 8.0
    elif rep["soft_pass"].get("soft_pass"):
        score += 3.0
    return float(score)


def sample_knobs(rng: random.Random) -> dict:
    return {k: rng.choice(v) for k, v in TUNE_SPACE.items()}


def cfg_from_knobs(knobs: dict) -> StructureGateConfig:
    base = StructureGateConfig.v13()
    # keep index_lean symmetric-ish with stock_led when tuned
    stock_led = float(knobs["stock_led_min_trail"])
    return replace(
        base,
        mode_hysteresis_enabled=True,
        risk_override_enabled=True,
        mode_enter_trail=float(knobs["mode_enter_trail"]),
        mode_exit_trail=float(knobs["mode_exit_trail"]),
        mode_switch_cooldown_days=int(knobs["mode_switch_cooldown_days"]),
        risk_override_stock_1d=float(knobs["risk_override_stock_1d"]),
        mild_defense_dd=float(knobs["mild_defense_dd"]),
        mild_defense_ret20=float(knobs["mild_defense_ret20"]),
        harsh_defense_dd=float(knobs["harsh_defense_dd"]),
        harsh_defense_ret20=float(knobs["harsh_defense_ret20"]),
        stock_led_min_trail=stock_led,
        index_lean_max_trail=-stock_led,
        sma50_hysteresis=float(knobs["sma50_hysteresis"]),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune", type=int, default=36, help="random trials for v13 knobs")
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    want = sorted(
        {"SPY", "QQQ", "SMH"}
        | set(book_members("QQQ"))
        | set(book_members("SMH"))
        | set(book_members("SPY"))
    )
    print(f"loading {len(want)} symbols…", flush=True)
    frames = load_many(want)
    for b in WEIGHTS:
        if b not in frames:
            raise SystemExit(f"missing {b}")

    # --- baseline v11 ---
    v11_reps = []
    cfg_v11 = StructureGateConfig.v11()
    for a, b in WINDOWS:
        print(f"\n=== v11 {a.date()}→{b.date()} ===", flush=True)
        rep = run_blend(frames, cfg_v11, a, b, label="v11")
        v11_reps.append(rep)
        bl = rep["blend"]
        print(
            f"  ret={bl['total_return']*100:6.2f}% maxDD={bl['max_drawdown']*100:6.2f}% "
            f"sharpe={bl['sharpe']:.2f} vsSPY={bl['vs_spy_bh_pp']:+.1f}pp "
            f"vsStatic={bl['vs_static_etf_blend_pp']:+.1f}pp trades={bl['n_trades']}",
            flush=True,
        )

    # --- tune v13 ---
    rng = random.Random(args.seed)
    trials = []
    # Always include canonical v13 defaults as trial 0
    default_knobs = {k: getattr(StructureGateConfig.v13(), k) for k in TUNE_KEYS}
    candidates = [default_knobs] + [sample_knobs(rng) for _ in range(max(0, args.tune - 1))]

    best = None
    for i, knobs in enumerate(candidates):
        cfg = cfg_from_knobs(knobs)
        window_reps = []
        scores = []
        for a, b in WINDOWS:
            rep = run_blend(frames, cfg, a, b, label=f"v13_t{i}")
            window_reps.append(rep)
            scores.append(score_report(rep))
        mean_score = float(sum(scores) / len(scores))
        # Guardrail: do not collapse the strong 2025 window too hard vs v11
        v11_2025 = next(r for r in v11_reps if r["start"] == "2025-08-07")
        v13_2025 = next(r for r in window_reps if r["start"] == "2025-08-07")
        ret_penalty = 0.0
        if v13_2025["blend"]["total_return"] < v11_2025["blend"]["total_return"] - 0.25:
            ret_penalty = 25.0
        # Prefer improving 2023 vs static gap
        v11_2023 = next(r for r in v11_reps if r["start"] == "2023-01-01")
        v13_2023 = next(r for r in window_reps if r["start"] == "2023-01-01")
        improve_2023 = (
            v13_2023["blend"]["vs_static_etf_blend_pp"]
            - v11_2023["blend"]["vs_static_etf_blend_pp"]
        )
        total = mean_score + 0.25 * improve_2023 - ret_penalty
        row = {
            "trial": i,
            "score": total,
            "mean_window_score": mean_score,
            "improve_2023_vs_static_pp": improve_2023,
            "knobs": knobs,
            "windows": [
                {
                    "start": r["start"],
                    "end": r["end"],
                    "total_return": r["blend"]["total_return"],
                    "max_drawdown": r["blend"]["max_drawdown"],
                    "sharpe": r["blend"]["sharpe"],
                    "vs_spy_bh_pp": r["blend"]["vs_spy_bh_pp"],
                    "vs_static_etf_blend_pp": r["blend"]["vs_static_etf_blend_pp"],
                    "n_trades": r["blend"]["n_trades"],
                    "soft_pass": r["soft_pass"].get("soft_pass"),
                    "hard_pass": r["soft_pass"].get("hard_pass_beat_both"),
                }
                for r in window_reps
            ],
        }
        trials.append(row)
        print(
            f"trial {i:02d} score={total:7.2f} "
            f"2023_ret={v13_2023['blend']['total_return']*100:5.1f}% "
            f"2025_ret={v13_2025['blend']['total_return']*100:5.1f}% "
            f"knobs={knobs}",
            flush=True,
        )
        if best is None or total > best["score"]:
            best = row

    assert best is not None
    best_cfg = cfg_from_knobs(best["knobs"])
    # Final labeled runs for best v13
    v13_reps = []
    for a, b in WINDOWS:
        print(f"\n=== v13_best {a.date()}→{b.date()} ===", flush=True)
        rep = run_blend(frames, best_cfg, a, b, label="v13")
        v13_reps.append(rep)
        bl = rep["blend"]
        print(
            f"  ret={bl['total_return']*100:6.2f}% maxDD={bl['max_drawdown']*100:6.2f}% "
            f"sharpe={bl['sharpe']:.2f} vsSPY={bl['vs_spy_bh_pp']:+.1f}pp "
            f"vsStatic={bl['vs_static_etf_blend_pp']:+.1f}pp trades={bl['n_trades']}",
            flush=True,
        )

    # Persist v13() defaults to the tuned knobs for reproducibility in report
    # (code default stays canonical; report records tuned values).
    summary = {
        "ok": True,
        "design": {
            "v11": "StructureGateConfig.v11() (== v8 knobs), blend 40/30/30",
            "v13": (
                "v11 blend + mode hysteresis (enter/exit trail) + "
                "soft-switch cooldown + risk override (harsh / stock 1d crash)"
            ),
            "weights": dict(V11_BOOK_WEIGHTS),
            "tune_keys": TUNE_KEYS,
        },
        "v11": v11_reps,
        "v13_default_knobs": default_knobs,
        "v13_best_knobs": best["knobs"],
        "v13_best_score": best["score"],
        "v13": v13_reps,
        "compare": [],
        "top_trials": sorted(trials, key=lambda r: r["score"], reverse=True)[:10],
    }
    for v11r, v13r in zip(v11_reps, v13_reps):
        summary["compare"].append(
            {
                "start": v11r["start"],
                "end": v11r["end"],
                "v11_ret": v11r["blend"]["total_return"],
                "v13_ret": v13r["blend"]["total_return"],
                "delta_ret_pp": (v13r["blend"]["total_return"] - v11r["blend"]["total_return"])
                * 100,
                "v11_maxdd": v11r["blend"]["max_drawdown"],
                "v13_maxdd": v13r["blend"]["max_drawdown"],
                "delta_maxdd_pp": (
                    v13r["blend"]["max_drawdown"] - v11r["blend"]["max_drawdown"]
                )
                * 100,
                "v11_sharpe": v11r["blend"]["sharpe"],
                "v13_sharpe": v13r["blend"]["sharpe"],
                "v11_vs_spy_pp": v11r["blend"]["vs_spy_bh_pp"],
                "v13_vs_spy_pp": v13r["blend"]["vs_spy_bh_pp"],
                "v11_vs_static_pp": v11r["blend"]["vs_static_etf_blend_pp"],
                "v13_vs_static_pp": v13r["blend"]["vs_static_etf_blend_pp"],
                "v11_trades": v11r["blend"]["n_trades"],
                "v13_trades": v13r["blend"]["n_trades"],
            }
        )

    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float) + "\n")
    (OUT / "trials.json").write_text(json.dumps(trials, indent=2, default=float) + "\n")
    (OUT / "v13_best_config.json").write_text(
        json.dumps(
            {
                "preset": "v13_tuned",
                "knobs": best["knobs"],
                "full_config": {k: getattr(best_cfg, k) for k in asdict(best_cfg) if k != "ers_config"},
            },
            indent=2,
            default=float,
        )
        + "\n"
    )

    # Human paste report
    lines = [
        "=== Structure Gate v13 vs v11 bakeoff ===",
        f"tune_trials={len(candidates)} seed={args.seed}",
        f"best_knobs={json.dumps(best['knobs'])}",
        "",
    ]
    for c in summary["compare"]:
        lines.append(f"## {c['start']} → {c['end']}")
        lines.append(
            f"v11: ret={c['v11_ret']*100:.2f}% maxDD={c['v11_maxdd']*100:.2f}% "
            f"sharpe={c['v11_sharpe']:.2f} vsSPY={c['v11_vs_spy_pp']:+.1f}pp "
            f"vsStatic={c['v11_vs_static_pp']:+.1f}pp trades={c['v11_trades']}"
        )
        lines.append(
            f"v13: ret={c['v13_ret']*100:.2f}% maxDD={c['v13_maxdd']*100:.2f}% "
            f"sharpe={c['v13_sharpe']:.2f} vsSPY={c['v13_vs_spy_pp']:+.1f}pp "
            f"vsStatic={c['v13_vs_static_pp']:+.1f}pp trades={c['v13_trades']}"
        )
        lines.append(
            f"Δ(v13-v11): ret={c['delta_ret_pp']:+.2f}pp maxDD={c['delta_maxdd_pp']:+.2f}pp "
            f"trades={c['v13_trades']-c['v11_trades']:+d}"
        )
        lines.append("")
    report = "\n".join(lines)
    (OUT / "compare_report.txt").write_text(report + "\n")
    print("\n" + report)
    print("wrote", OUT / "summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
