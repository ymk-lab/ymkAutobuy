#!/usr/bin/env python3
"""Attribute v13 sleeve returns by mode time: $ and pp per 1% of days.

Usage (on VPS with paper cache)::

    .venv/bin/python examples/report_v13_mode_return_per_pct.py 2025-08-07 2026-08-07
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.strategy.structure_gate import V13_BOOK_WEIGHTS, StructureGateConfig
from run_structure_gate_v13_blend import (  # type: ignore
    CAPITAL,
    OUT,
    WEIGHTS,
    book_members,
    load_many,
    run_book,
)

BUCKETS = {
    "ETF(bench)": ("bench",),
    "個股(ers+strong)": ("ers", "strong"),
    "CASH": ("cash",),
}


def attr_sleeve(sim, *, sleeve_cap: float) -> dict:
    eq = sim.equity.astype(float).dropna()
    mode = sim.mode.reindex(eq.index).ffill()
    # Next-open execution: today's mode earns tomorrow's equity change.
    day_pnl = eq.diff()
    decision = mode.shift(1)
    rows = []
    n = max(int(decision.notna().sum()), 1)
    for label, modes in BUCKETS.items():
        mask = decision.isin(modes)
        days = int(mask.sum())
        pnl = float(day_pnl.where(mask).sum())
        # Compound path return while in bucket (chain of daily rets on those days)
        rets = eq.pct_change().where(mask)
        # Sum of arithmetic daily contrib ≈ pnl/start for attribution; also show $
        time_pct = 100.0 * days / n
        ret_on_cap = 100.0 * pnl / sleeve_cap
        per_time_pct = (ret_on_cap / time_pct) if time_pct > 1e-9 else float("nan")
        usd_per_time_pct = (pnl / time_pct) if time_pct > 1e-9 else float("nan")
        rows.append(
            {
                "bucket": label,
                "days": days,
                "time_pct": time_pct,
                "pnl_usd": pnl,
                "ret_pp_on_sleeve_cap": ret_on_cap,
                "ret_pp_per_1pct_time": per_time_pct,
                "usd_per_1pct_time": usd_per_time_pct,
            }
        )
    total_pnl = float(eq.iloc[-1] - eq.iloc[0])
    return {
        "start_equity": float(eq.iloc[0]),
        "end_equity": float(eq.iloc[-1]),
        "total_pnl_usd": total_pnl,
        "total_return_pp": 100.0 * total_pnl / sleeve_cap,
        "usd_per_1pp_total_return": sleeve_cap / 100.0,
        "buckets": rows,
    }


def main() -> int:
    start = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2025-08-07")
    end = pd.Timestamp(sys.argv[2] if len(sys.argv) > 2 else "2026-08-07")
    want = sorted(set(WEIGHTS) | {m for b in WEIGHTS for m in book_members(b)})
    print(f"loading {len(want)} symbols…", flush=True)
    frames = load_many(want)
    for b in WEIGHTS:
        if b not in frames:
            raise SystemExit(f"missing {b}")

    cfg = StructureGateConfig.v13()
    report = {
        "start": str(start.date()),
        "end": str(end.date()),
        "capital": CAPITAL,
        "weights": dict(WEIGHTS),
        "sleeves": {},
        "blend_note": "袖口獨立資本；組合加權=各袖口 bucket 金額加總後再／50k",
    }

    blend_bucket_pnl = {k: 0.0 for k in BUCKETS}
    blend_bucket_days = {k: 0 for k in BUCKETS}
    blend_days = 0

    print(f"\n=== v13 mode 報酬密度 {start.date()}→{end.date()} ===")
    print("（決策日 mode → 次日權益變動；每%時間 = 該狀態佔交易日 1 個百分點）\n")

    for book, w in WEIGHTS.items():
        sleeve_cap = CAPITAL * w
        sim, _bh, n_mem = run_book(
            book, frames, sleeve_capital=sleeve_cap, start=start, end=end, cfg=cfg
        )
        att = attr_sleeve(sim, sleeve_cap=sleeve_cap)
        report["sleeves"][book] = {"weight": w, "n_members": n_mem, **att}
        print(
            f"## {book} 袖口 資本=${sleeve_cap:,.0f}  "
            f"總報酬 {att['total_return_pp']:+.1f}%  "
            f"（+${att['total_pnl_usd']:,.0f}；每 1% 總報酬 ≈ ${att['usd_per_1pp_total_return']:,.0f}）"
        )
        for row in att["buckets"]:
            print(
                f"  {row['bucket']:<18} 時間 {row['time_pct']:5.1f}%  "
                f"貢獻 {row['ret_pp_on_sleeve_cap']:+6.1f}pp / ${row['pnl_usd']:+,.0f}  "
                f"→ 每1%時間 {row['ret_pp_per_1pct_time']:+.2f}pp / ${row['usd_per_1pct_time']:+,.0f}"
            )
            blend_bucket_pnl[row["bucket"]] += row["pnl_usd"]
            blend_bucket_days[row["bucket"]] += row["days"]
            blend_days = max(blend_days, row["days"] + int(round((100 - row["time_pct"]) / 100 * (row["days"] / max(row["time_pct"], 1e-9)))))
        # track day count from first sleeve length
        if book == list(WEIGHTS)[0]:
            blend_days = int(sim.mode.reindex(sim.equity.dropna().index).shift(1).notna().sum())
        print()

    print(f"## 組合（${CAPITAL:,.0f} 加總袖口）")
    total_pnl = sum(blend_bucket_pnl.values())
    print(
        f"  總報酬 {100*total_pnl/CAPITAL:+.1f}%（+${total_pnl:,.0f}；"
        f"每 1% 總報酬 ≈ ${CAPITAL/100:,.0f}）"
    )
    blend_buckets = []
    n = max(blend_days, 1)
    # Recompute time% as capital-weighted average of sleeve time%
    for label in BUCKETS:
        # capital-weighted time
        time_pct = 0.0
        for book, w in WEIGHTS.items():
            b = report["sleeves"][book]
            row = next(r for r in b["buckets"] if r["bucket"] == label)
            time_pct += float(w) * float(row["time_pct"])
        pnl = blend_bucket_pnl[label]
        ret_pp = 100.0 * pnl / CAPITAL
        per = (ret_pp / time_pct) if time_pct > 1e-9 else float("nan")
        usd_per = (pnl / time_pct) if time_pct > 1e-9 else float("nan")
        blend_buckets.append(
            {
                "bucket": label,
                "time_pct": time_pct,
                "pnl_usd": pnl,
                "ret_pp_on_capital": ret_pp,
                "ret_pp_per_1pct_time": per,
                "usd_per_1pct_time": usd_per,
            }
        )
        print(
            f"  {label:<18} 時間 {time_pct:5.1f}%  "
            f"貢獻 {ret_pp:+6.1f}pp / ${pnl:+,.0f}  "
            f"→ 每1%時間 {per:+.2f}pp / ${usd_per:+,.0f}"
        )

    report["blend"] = {
        "total_pnl_usd": total_pnl,
        "total_return_pp": 100.0 * total_pnl / CAPITAL,
        "usd_per_1pp_total_return": CAPITAL / 100.0,
        "buckets": blend_buckets,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"mode_return_density_{start.date()}_{end.date()}.json"
    out_path.write_text(json.dumps(report, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
