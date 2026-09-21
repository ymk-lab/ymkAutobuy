#!/usr/bin/env python3
"""Structure Gate v13 calendar-year walk helper.

Paper weights: SPY 50% / QQQ 50%. Config: StructureGateConfig.v13().
Delegates each year to run_structure_gate_v13_blend.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLEND = ROOT / "examples" / "run_structure_gate_v13_blend.py"
YEARS = [
    ("2019-01-01", "2020-01-01"),
    ("2020-01-01", "2021-01-01"),
    ("2021-01-01", "2022-01-01"),
    ("2022-01-01", "2023-01-01"),
    ("2023-01-01", "2024-01-01"),
    ("2024-01-01", "2025-01-01"),
    ("2025-01-01", "2026-01-01"),
    ("2026-01-01", "2026-09-21"),
]


def main() -> int:
    py = sys.executable
    if not BLEND.is_file():
        print(f"missing {BLEND}", file=sys.stderr)
        return 2
    rc = 0
    for start, end in YEARS:
        print(f"\n===== YEAR {start[:4]} {start}->{end} =====", flush=True)
        proc = subprocess.run([py, str(BLEND), start, end], cwd=str(ROOT))
        if proc.returncode != 0:
            rc = proc.returncode
            print(f"year {start[:4]} failed rc={proc.returncode}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
