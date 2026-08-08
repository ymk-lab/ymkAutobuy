#!/usr/bin/env python3
"""Extend existing Structure Gate OHLCV caches with earlier warmup bars."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.data.loader import validate_ohlcv
from run_emerging_rs_wave_gates import UNIVERSE as QQQ_UNIVERSE  # type: ignore
from run_emerging_rs_wave_soxx import UNIVERSE as SEMI_UNIVERSE  # type: ignore

BOOKS = {
    "QQQ": {
        "bench": "QQQ",
        "universe": list(QQQ_UNIVERSE),
        "cache": ROOT / "examples/data/emerging_rs_wave_qqq_g1_longbridge/cache_ohlcv",
    },
    "SOXX": {
        "bench": "SOXX",
        "universe": list(SEMI_UNIVERSE),
        "cache": ROOT / "examples/data/emerging_rs_wave_soxx/cache_ohlcv",
    },
    "SPY": {
        "bench": "SPY",
        "universe": None,
        "universe_file": ROOT / "examples/data/emerging_rs_wave_spy/universe.txt",
        "cache": ROOT / "examples/data/emerging_rs_wave_spy/cache_ohlcv",
    },
}


def normalize(raw: pd.DataFrame) -> pd.DataFrame | None:
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.copy()
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw = raw.copy()
        raw.columns = [str(c).lower() for c in raw.columns]
    need = ["open", "high", "low", "close", "volume"]
    if any(c not in raw.columns for c in need):
        return None
    cleaned = raw[need].dropna()
    ok = (cleaned["high"] >= cleaned[["open", "close"]].max(axis=1)) & (
        cleaned["low"] <= cleaned[["open", "close"]].min(axis=1)
    )
    cleaned = cleaned.loc[ok]
    if cleaned.empty:
        return None
    try:
        df = validate_ohlcv(cleaned)
    except ValueError:
        return None
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[~df.index.duplicated(keep="last")].sort_index()


def merge_save(path: Path, new: pd.DataFrame) -> int:
    if path.is_file() and path.stat().st_size > 64:
        old = pd.read_csv(path, index_col=0, parse_dates=True)
        old.columns = [str(c).lower() for c in old.columns]
        old = old[["open", "high", "low", "close", "volume"]].dropna()
        old.index = pd.to_datetime(old.index).tz_localize(None).normalize()
        merged = pd.concat([old, new]).sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]
    else:
        merged = new
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(path)
    return len(merged)


def download_batch(tickers: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    raw = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if raw is not None and not raw.empty and isinstance(raw.columns, pd.MultiIndex):
        level0 = set(raw.columns.get_level_values(0).unique())
        for sym in tickers:
            if sym not in level0:
                continue
            df = normalize(raw[sym].dropna(how="all"))
            if df is not None and len(df) >= 100:
                out[sym] = df
    missing = [t for t in tickers if t not in out]
    for i, sym in enumerate(missing):
        try:
            r = yf.download(sym, start=start, end=end, auto_adjust=True, progress=False)
        except Exception:
            continue
        df = normalize(r)
        if df is not None and len(df) >= 100:
            out[sym] = df
        if (i + 1) % 25 == 0:
            print(f"  fallback {i+1}/{len(missing)}")
    return out


def universe_for(book: str) -> list[str]:
    spec = BOOKS[book]
    if spec.get("universe"):
        return list(spec["universe"])
    uf = Path(spec["universe_file"])
    return [
        ln.strip()
        for ln in uf.read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]


def refetch_book(book: str, start: str, end: str) -> None:
    spec = BOOKS[book]
    cache: Path = spec["cache"]
    members = universe_for(book)
    tickers = sorted({spec["bench"], *members})
    print(f"\n=== {book} tickers={len(tickers)} -> {cache} ===")
    # chunk to keep yfinance happier on large universes
    panel: dict[str, pd.DataFrame] = {}
    chunk = 80
    for i in range(0, len(tickers), chunk):
        part = tickers[i : i + chunk]
        print(f"  download {i+1}-{i+len(part)}/{len(tickers)}")
        panel.update(download_batch(part, start, end))
    if spec["bench"] not in panel:
        raise SystemExit(f"{book}: bench {spec['bench']} download failed")
    n_ok = 0
    for sym, df in panel.items():
        merge_save(cache / f"{sym}.csv", df)
        n_ok += 1
    print(f"saved={n_ok} missing={len(tickers) - n_ok}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("books", nargs="*", default=["QQQ", "SOXX", "SPY"])
    ap.add_argument("--start", default="2021-06-01")
    ap.add_argument("--end", default="2026-01-05")
    args = ap.parse_args()
    for b in [x.strip().upper() for x in args.books]:
        if b not in BOOKS:
            raise SystemExit(f"unknown book {b}; choose from {sorted(BOOKS)}")
        refetch_book(b, args.start, args.end)
    print("\nDone.")


if __name__ == "__main__":
    main()
