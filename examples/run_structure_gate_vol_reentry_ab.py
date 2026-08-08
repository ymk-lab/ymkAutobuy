#!/usr/bin/env python3
"""A/B: v8 vs vol-adaptive mild vs reentry vs both (default books SOXX)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.strategy.structure_gate import StructureGateConfig
from run_structure_gate_bakeoff import run_book  # type: ignore

OUT = ROOT / "examples" / "data" / "structure_gate_vol_reentry_ab"
START = pd.Timestamp("2023-01-01")
END = pd.Timestamp("2025-12-31")

VARIANTS: dict[str, StructureGateConfig] = {
    "v8": StructureGateConfig(),
    "vol_mild": StructureGateConfig(mild_vol_adaptive=True),
    "reentry": StructureGateConfig(reentry_force_bench=True),
    "vol_mild_reentry": StructureGateConfig(
        mild_vol_adaptive=True, reentry_force_bench=True
    ),
}


def main() -> None:
    books = [a.strip().upper() for a in sys.argv[1:]] or ["SOXX"]
    fees = FutuUsEquityFees(slippage_bps=3.0)
    OUT.mkdir(parents=True, exist_ok=True)

    table: list[dict] = []
    for book in books:
        for name, cfg in VARIANTS.items():
            out_root = OUT / name
            print(f"\n##### {book} / {name} #####")
            rep = run_book(
                book, fees, cfg, start=START, end=END, out_root=out_root
            )
            sg = rep["structure_gate"]
            modes = rep["mode_distribution"]
            table.append(
                {
                    "book": book,
                    "variant": name,
                    "total_return": sg["total_return"],
                    "max_drawdown": sg["max_drawdown"],
                    "sharpe": sg["sharpe"],
                    "vs_bh_pp": rep["vs_bh_pp"],
                    "vs_ers_pp": rep["vs_ers_pp"],
                    "soft_pass": rep["soft_pass"],
                    "hard_pass": rep["hard_pass_beat_both"],
                    "cash_pct": modes.get("cash", 0.0) * 100,
                    "bench_pct": modes.get("bench", 0.0) * 100,
                    "ers_pct": modes.get("ers", 0.0) * 100,
                    "sticky_cov": rep["sticky_audit"]["sticky_coverage"] * 100,
                    "thrust_cov": rep["sticky_audit"]["thrust_coverage"] * 100,
                    "config": {
                        "mild_vol_adaptive": cfg.mild_vol_adaptive,
                        "reentry_force_bench": cfg.reentry_force_bench,
                        "mild_vol_dd_k": cfg.mild_vol_dd_k,
                        "mild_vol_ret20_k": cfg.mild_vol_ret20_k,
                        "reentry_ret5_min": cfg.reentry_ret5_min,
                        "reentry_bounce20_min": cfg.reentry_bounce20_min,
                    },
                }
            )

    df = pd.DataFrame(table)
    cols = [
        "book",
        "variant",
        "total_return",
        "max_drawdown",
        "sharpe",
        "vs_bh_pp",
        "soft_pass",
        "hard_pass",
        "cash_pct",
        "bench_pct",
    ]
    print("\n=== A/B SUMMARY ===")
    print(df[cols].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    payload = {
        "window": [str(START.date()), str(END.date())],
        "rule_base": "structure_gate_v8_universal_tune",
        "variants": list(VARIANTS),
        "rows": table,
    }
    (OUT / "ab_summary.json").write_text(
        json.dumps(payload, indent=2, default=float) + "\n"
    )
    print(f"wrote {OUT / 'ab_summary.json'}")


if __name__ == "__main__":
    main()
