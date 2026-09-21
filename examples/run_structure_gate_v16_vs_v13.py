#!/usr/bin/env python3
"""Structure Gate v16 vs v13 (SPY50/QQQ50) on 2025–2026 window.

v16 = v13 locks/defense + dual trail 20/70 (sticky/strong/ers_lag were 60).

Usage::

    PYTHONPATH=src:examples python examples/run_structure_gate_v16_vs_v13.py
    PYTHONPATH=src:examples python examples/run_structure_gate_v16_vs_v13.py 2025-08-07 2026-08-13
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.strategy.structure_gate import (  # noqa: E402
    V13_BOOK_WEIGHTS,
    V16_BOOK_WEIGHTS,
    StructureGateConfig,
    blend_structure_gate_books,
)
from run_emerging_rs_wave_gates import metrics  # type: ignore  # noqa: E402
from run_structure_gate_bakeoff import soft_pass  # type: ignore  # noqa: E402
from run_structure_gate_v13_blend import (  # type: ignore  # noqa: E402
    CAPITAL,
    book_members,
    load_many,
    run_book,
)

OUT = ROOT / "examples" / "data" / "structure_gate_v16_vs_v13"


def run_preset(
    label: str,
    cfg: StructureGateConfig,
    weights: dict[str, float],
    frames: dict,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict:
    book_sims = {}
    sleeves = []
    print(f"\n=== {label} {start.date()}→{end.date()} weights={weights} ===", flush=True)
    for book, w in weights.items():
        sleeve_cap = CAPITAL * w
        sim, bh, n_mem = run_book(
            book, frames, sleeve_capital=sleeve_cap, start=start, end=end, cfg=cfg
        )
        book_sims[book] = sim
        m = metrics(sim.equity, sleeve_cap)
        mb = metrics(bh, sleeve_cap)
        modes = sim.mode.value_counts(normalize=True).to_dict()
        blocked = float(sim.meta.get("mode_switch_blocked", pd.Series(dtype=float)).mean() or 0.0)
        row = {
            "book": book,
            "weight": w,
            "n_members": n_mem,
            "total_return": m["total_return"],
            "max_drawdown": m["max_drawdown"],
            "sharpe": m["sharpe"],
            "bh_total_return": mb["total_return"],
            "mode_distribution": modes,
            "n_trades": int(len(sim.trades)),
            "mode_switch_blocked_share": blocked,
        }
        sleeves.append(row)
        print(
            f"  {book:4} SG={m['total_return']*100:7.2f}% BH={mb['total_return']*100:6.2f}% "
            f"maxDD={m['max_drawdown']*100:6.2f}% trades={row['n_trades']} "
            f"modes={ {k: round(v*100,1) for k,v in modes.items()} }",
            flush=True,
        )
        sim.equity.to_csv(OUT / f"equity_{label}_{book}_{start.date()}_{end.date()}.csv", header=["equity"])

    blended, panel = blend_structure_gate_books(book_sims, weights, capital=CAPITAL)
    blended = blended.loc[start:end].dropna()
    m_b = metrics(blended, CAPITAL)
    from qresearch.backtest.futu_costs import FutuUsEquityFees
    from qresearch.strategy.regime_playbook import simulate_bench_bh

    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    spy = frames["SPY"]
    eq_bh = (
        simulate_bench_bh(spy["open"], spy["close"], capital=CAPITAL, start=start, fees=fees)
        .reindex(blended.index)
        .ffill()
    )
    m_bh = metrics(eq_bh, CAPITAL)
    etf_eq = []
    for book, w in weights.items():
        bdf = frames[book]
        etf_eq.append(
            simulate_bench_bh(
                bdf["open"], bdf["close"], capital=CAPITAL * w, start=start, fees=fees
            )
        )
    static = pd.concat(etf_eq, axis=1).ffill().sum(axis=1).reindex(blended.index).ffill()
    m_static = metrics(static, CAPITAL)
    gate = soft_pass(m_b["total_return"], m_bh["total_return"], m_static["total_return"])
    blended.to_csv(OUT / f"equity_{label}_blend_{start.date()}_{end.date()}.csv", header=["equity"])
    out = {
        "label": label,
        "start": str(start.date()),
        "end": str(end.date()),
        "weights": weights,
        "cfg": {
            "leadership_trail_days": cfg.leadership_trail_days,
            "sticky_trail_days": cfg.sticky_trail_days,
            "strong_lookback": cfg.strong_lookback,
            "ers_lag_lookback": cfg.ers_lag_lookback,
            "mode_enter_trail": cfg.mode_enter_trail,
            "mode_exit_trail": cfg.mode_exit_trail,
            "mode_switch_cooldown_days": cfg.mode_switch_cooldown_days,
        },
        "blend": {
            "total_return": m_b["total_return"],
            "max_drawdown": m_b["max_drawdown"],
            "sharpe": m_b["sharpe"],
            "end_equity": m_b["end_equity"],
            "vs_spy_bh_pp": (m_b["total_return"] - m_bh["total_return"]) * 100,
            "vs_static_etf_blend_pp": (m_b["total_return"] - m_static["total_return"]) * 100,
            "n_trades": int(sum(s["n_trades"] for s in sleeves)),
        },
        "spy_bh": {
            "total_return": m_bh["total_return"],
            "max_drawdown": m_bh["max_drawdown"],
            "sharpe": m_bh["sharpe"],
        },
        "static_etf": {
            "total_return": m_static["total_return"],
            "max_drawdown": m_static["max_drawdown"],
            "sharpe": m_static["sharpe"],
        },
        "soft_pass": gate,
        "sleeves": sleeves,
    }
    print(
        f"  BLEND {label}: {m_b['total_return']*100:+.2f}% maxDD={m_b['max_drawdown']*100:.2f}% "
        f"vsSPY={out['blend']['vs_spy_bh_pp']:+.1f}pp vsStatic={out['blend']['vs_static_etf_blend_pp']:+.1f}pp "
        f"trades={out['blend']['n_trades']}",
        flush=True,
    )
    return out


def main() -> int:
    start = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2025-08-07")
    end = pd.Timestamp(sys.argv[2] if len(sys.argv) > 2 else "2026-08-13")
    OUT.mkdir(parents=True, exist_ok=True)

    want = sorted(
        set(V13_BOOK_WEIGHTS)
        | set(V16_BOOK_WEIGHTS)
        | {m for b in V13_BOOK_WEIGHTS for m in book_members(b)}
    )
    print(f"loading {len(want)} symbols…", flush=True)
    frames = load_many(want)
    for b in V13_BOOK_WEIGHTS:
        if b not in frames:
            raise SystemExit(f"missing {b}")

    v13 = run_preset("v13", StructureGateConfig.v13(), dict(V13_BOOK_WEIGHTS), frames, start, end)
    v16 = run_preset("v16", StructureGateConfig.v16(), dict(V16_BOOK_WEIGHTS), frames, start, end)

    delta = {
        "ret_pp": (v16["blend"]["total_return"] - v13["blend"]["total_return"]) * 100,
        "maxdd_pp": (v16["blend"]["max_drawdown"] - v13["blend"]["max_drawdown"]) * 100,
        "trades": v16["blend"]["n_trades"] - v13["blend"]["n_trades"],
        "vs_spy_pp": v16["blend"]["vs_spy_bh_pp"] - v13["blend"]["vs_spy_bh_pp"],
    }
    report = {
        "window": [str(start.date()), str(end.date())],
        "capital": CAPITAL,
        "v13": v13,
        "v16": v16,
        "delta_v16_minus_v13": delta,
        "note": (
            "v16: sticky_trail/strong/ers_lag lookback 60→70 (trail 20/70); "
            "mode hysteresis & defense unchanged from v13"
        ),
    }
    out_json = OUT / f"compare_{start.date()}_{end.date()}.json"
    out_json.write_text(json.dumps(report, indent=2, default=float) + "\n")

    lines = [
        "=== Structure Gate v16 vs v13 ===",
        f"窗：{start.date()} → {end.date()}｜資本 ${CAPITAL:,.0f}｜權重 SPY50/QQQ50",
        "",
        f"v13 (20/60): {v13['blend']['total_return']*100:+.2f}%｜maxDD {v13['blend']['max_drawdown']*100:.2f}%｜"
        f"trades {v13['blend']['n_trades']}｜vsSPY {v13['blend']['vs_spy_bh_pp']:+.1f}pp",
        f"v16 (20/70): {v16['blend']['total_return']*100:+.2f}%｜maxDD {v16['blend']['max_drawdown']*100:.2f}%｜"
        f"trades {v16['blend']['n_trades']}｜vsSPY {v16['blend']['vs_spy_bh_pp']:+.1f}pp",
        f"Δ(v16−v13): ret {delta['ret_pp']:+.2f}pp｜maxDD {delta['maxdd_pp']:+.2f}pp｜trades {delta['trades']:+d}",
        "",
        "v16 規則：雙窗 trail 20/70（sticky/strong/ers_lag 長窗 60→70）；模式滯後與防守同 v13。",
    ]
    txt = "\n".join(lines) + "\n"
    (OUT / f"compare_{start.date()}_{end.date()}_zhTW.txt").write_text(txt, encoding="utf-8")
    print("\n" + txt)
    print(f"wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
