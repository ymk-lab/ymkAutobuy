#!/usr/bin/env python3
"""Bootstrap full v11 OHLCV cache (SPY500 + QQQ + SMH) via Yahoo Finance.

Use on lean local installs so blend backtest / paper signal see the full
universes (not just the ~120 names from the first light bootstrap).

  python examples/bootstrap_v11_full_cache.py
  python examples/bootstrap_v11_full_cache.py --benches-only
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.data.loader import validate_ohlcv
from run_emerging_rs_wave_gates import UNIVERSE as QQQ_UNIVERSE  # type: ignore
from run_emerging_rs_wave_soxx import UNIVERSE as SEMI_UNIVERSE  # type: ignore
from run_structure_gate_v8_paper_daily import MIN_BARS, load_cache, save_cache  # type: ignore

OUT = ROOT / "examples" / "data" / "structure_gate_v11_paper" / "cache_ohlcv"
START = "2021-06-01"


def spy_universe() -> list[str]:
    uf = ROOT / "examples/data/emerging_rs_wave_spy/universe.txt"
    if not uf.is_file():
        return []
    return [
        ln.strip().upper()
        for ln in uf.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#") and ln.strip().upper() != "SPY"
    ]


def want_symbols(*, benches_only: bool) -> list[str]:
    benches = ["SPY", "QQQ", "SMH"]
    if benches_only:
        return benches
    return sorted(
        set(benches)
        | {s for s in QQQ_UNIVERSE if s != "QQQ"}
        | {s for s in SEMI_UNIVERSE if s != "SMH"}
        | set(spy_universe())
    )


def fetch_one(symbol: str) -> pd.DataFrame | None:
    import yfinance as yf

    raw = yf.download(
        symbol,
        start=START,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw is None or len(raw) < MIN_BARS:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [str(c[0]).lower() for c in raw.columns]
    else:
        raw.columns = [str(c).lower() for c in raw.columns]
    need = ["open", "high", "low", "close", "volume"]
    if any(c not in raw.columns for c in need):
        return None
    df = validate_ohlcv(raw[need].dropna())
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if len(df) < MIN_BARS:
        return None
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description="Bootstrap full v11 OHLCV cache")
    ap.add_argument("--benches-only", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-download even if cache exists")
    ap.add_argument("--sleep", type=float, default=0.05, help="pause between downloads")
    args = ap.parse_args()

    try:
        import yfinance  # noqa: F401
    except ImportError:
        print("pip install yfinance")
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    symbols = want_symbols(benches_only=args.benches_only)
    print(f"target={len(symbols)} out={OUT} force={args.force}")

    n_ok = n_skip = n_fail = 0
    t0 = time.time()
    for i, sym in enumerate(symbols, 1):
        if not args.force and load_cache(OUT, sym) is not None:
            n_skip += 1
            if i == 1 or i % 50 == 0 or i == len(symbols):
                print(f"[{i}/{len(symbols)}] ok={n_ok} skip={n_skip} fail={n_fail} last={sym}")
            continue
        try:
            df = fetch_one(sym)
            if df is None:
                n_fail += 1
                # permanent skip marker for bad OHLC (used by paper daily)
                (OUT / f"{sym}.skip").write_text("bad ohlcv\n", encoding="utf-8")
                print(f"FAIL {sym}")
            else:
                save_cache(OUT, sym, df)
                n_ok += 1
                skip = OUT / f"{sym}.skip"
                if skip.is_file():
                    skip.unlink()
        except Exception as exc:  # noqa: BLE001
            n_fail += 1
            print(f"FAIL {sym}: {exc}")
            (OUT / f"{sym}.skip").write_text(f"{exc}\n", encoding="utf-8")
        if args.sleep > 0:
            time.sleep(args.sleep)
        if i == 1 or i % 25 == 0 or i == len(symbols):
            elapsed = time.time() - t0
            print(
                f"[{i}/{len(symbols)}] ok={n_ok} skip={n_skip} fail={n_fail} "
                f"elapsed={elapsed/60:.1f}m last={sym}"
            )

    # Quarantine only CSVs that error on read (not merely short history).
    n_bad = 0
    for path in sorted(OUT.glob("*.csv")):
        if path.name.endswith(".bad.csv"):
            continue
        sym = path.stem.upper()
        try:
            raw = pd.read_csv(path, index_col=0, parse_dates=True)
            raw.columns = [str(c).lower() for c in raw.columns]
            need = ["open", "high", "low", "close", "volume"]
            if any(c not in raw.columns for c in need):
                raise ValueError("missing columns")
            validate_ohlcv(raw[need].dropna())
        except Exception as exc:  # noqa: BLE001
            bad = OUT / f"{sym}.bad.csv"
            try:
                path.replace(bad)
            except Exception:
                path.unlink(missing_ok=True)  # type: ignore[call-arg]
            (OUT / f"{sym}.skip").write_text(f"corrupt: {exc}\n", encoding="utf-8")
            n_bad += 1
    if n_bad:
        print(f"quarantined corrupt csv={n_bad}")

    # Summary counts for benches / books (never crash the whole job).
    for label, members in (
        ("SPY", ["SPY"] + spy_universe()),
        ("QQQ", ["QQQ"] + [s for s in QQQ_UNIVERSE if s != "QQQ"]),
        ("SMH", ["SMH"] + [s for s in SEMI_UNIVERSE if s != "SMH"]),
    ):
        have = 0
        for s in members:
            try:
                if load_cache(OUT, s) is not None:
                    have += 1
            except Exception:
                pass
        print(f"coverage {label}: {have}/{len(members)}")

    print(f"done ok={n_ok} skip={n_skip} fail={n_fail} → {OUT}")
    return 0 if n_ok or n_skip else 1


if __name__ == "__main__":
    raise SystemExit(main())
