#!/usr/bin/env python3
"""Scan Structure Gate OHLCV caches for corrupted price flips.

Distinguishes:
  - flip corruption: half↔double oscillations (AZN/HON-class merge bugs) → FAIL
  - high-vol spikes: real names like SMCI/CVNA → WARN only unless extreme
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CACHES = [
    ROOT / "examples/data/emerging_rs_wave_qqq_g1_longbridge/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_soxx/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_smh/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_spy/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_dia/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_iwm/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_hsi/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_hstech/cache_ohlcv",
]


def audit_file(
    path: Path,
    *,
    abs_ret: float,
    max_spike: int,
    max_flip: int,
) -> dict | None:
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    except Exception as exc:  # noqa: BLE001
        return {
            "path": str(path),
            "ticker": path.stem,
            "error": str(exc),
            "fail": True,
            "level": "fail",
        }
    cols = {str(c).lower(): c for c in df.columns}
    if "close" not in cols:
        return {
            "path": str(path),
            "ticker": path.stem,
            "error": "missing close",
            "fail": True,
            "level": "fail",
        }
    close = df[cols["close"]].astype(float)
    ret = close.pct_change().dropna()
    if ret.empty:
        return None
    ratio = close / close.shift(1)
    # Half then double (or reverse): classic adjust/merge pollution.
    flip = (
        ((ratio < 0.65) & (ratio.shift(-1) > 1.55))
        | ((ratio > 1.55) & (ratio.shift(-1) < 0.65))
    ).fillna(False)
    n_flip = int(flip.sum())
    spike = ret.abs() > abs_ret
    n_spike = int(spike.sum())

    level = None
    if n_flip > max_flip:
        level = "fail"
    elif n_spike > max_spike:
        level = "warn"
    if level is None:
        return None
    bad_idx = flip if level == "fail" else spike
    return {
        "path": str(path),
        "ticker": path.stem,
        "n_bars": int(len(close)),
        "flip_days": n_flip,
        "spike_days": n_spike,
        "max_abs_ret": float(ret.abs().max()),
        "worst_dates": [str(pd.Timestamp(d).date()) for d in bad_idx[bad_idx].index[:8]],
        "fail": level == "fail",
        "level": level,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("caches", nargs="*", type=Path)
    ap.add_argument("--abs-ret", type=float, default=0.25)
    ap.add_argument(
        "--max-spike",
        type=int,
        default=20,
        help="WARN if |ret| spikes exceed this (default 20)",
    )
    ap.add_argument(
        "--max-flip",
        type=int,
        default=8,
        help="FAIL if half/double flip pairs exceed this (default 8)",
    )
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()
    caches = [Path(c) for c in args.caches] or DEFAULT_CACHES

    reports: list[dict] = []
    fails: list[dict] = []
    warns: list[dict] = []
    scanned = 0
    for cache in caches:
        if not cache.is_dir():
            print(f"skip missing: {cache}")
            continue
        for path in sorted(cache.glob("*.csv")):
            scanned += 1
            row = audit_file(
                path,
                abs_ret=args.abs_ret,
                max_spike=args.max_spike,
                max_flip=args.max_flip,
            )
            if row is None:
                continue
            reports.append(row)
            if row["level"] == "fail":
                fails.append(row)
            else:
                warns.append(row)

    print(f"scanned={scanned} warn={len(warns)} fail={len(fails)}")
    for row in warns[:20]:
        print(
            f"WARN {row['ticker']}: spikes={row.get('spike_days')} "
            f"flips={row.get('flip_days')} max_abs={row.get('max_abs_ret'):.2f}"
        )
    for row in fails[:40]:
        print(
            f"FAIL {row['ticker']}: flips={row.get('flip_days')} "
            f"spikes={row.get('spike_days')} max_abs={row.get('max_abs_ret')} "
            f"path={row['path']}"
        )
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(
                {
                    "abs_ret": args.abs_ret,
                    "max_spike": args.max_spike,
                    "max_flip": args.max_flip,
                    "scanned": scanned,
                    "fails": fails,
                    "warns": warns,
                },
                indent=2,
            )
            + "\n"
        )
        print(f"wrote {args.json_out}")

    if fails:
        raise SystemExit(1)
    print("OK")


if __name__ == "__main__":
    main()
