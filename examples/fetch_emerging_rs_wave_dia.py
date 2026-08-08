#!/usr/bin/env python3
"""Fetch DIA + Dow 30 OHLCV into examples/data/emerging_rs_wave_dia/cache_ohlcv."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.data.loader import validate_ohlcv

OUT = ROOT / "examples" / "data" / "emerging_rs_wave_dia"
CACHE = OUT / "cache_ohlcv"

# Dow 30 after late-2024 reconstitution (NVDA/AMZN/SHW in).
DOW30 = [
    "AAPL",
    "AMGN",
    "AMZN",
    "AXP",
    "BA",
    "CAT",
    "CRM",
    "CSCO",
    "CVX",
    "DIS",
    "GS",
    "HD",
    "HON",
    "IBM",
    "JNJ",
    "JPM",
    "KO",
    "MCD",
    "MMM",
    "MRK",
    "MSFT",
    "NKE",
    "NVDA",
    "PG",
    "SHW",
    "TRV",
    "UNH",
    "V",
    "VZ",
    "WMT",
]


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


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    tickers = ["DIA"] + DOW30
    start, end = "2023-01-01", "2026-08-10"
    raw = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    saved: list[str] = []
    missing: list[str] = []
    if raw is not None and not raw.empty and isinstance(raw.columns, pd.MultiIndex):
        level0 = set(raw.columns.get_level_values(0).unique())
        for sym in tickers:
            if sym not in level0:
                missing.append(sym)
                continue
            df = normalize(raw[sym].dropna(how="all"))
            if df is None or len(df) < 220:
                missing.append(sym)
                continue
            df.to_csv(CACHE / f"{sym}.csv")
            saved.append(sym)
    (OUT / "universe.txt").write_text(
        "# Dow 30 constituents for DIA Structure Gate\n" + "\n".join(DOW30) + "\n"
    )
    print(f"saved={len(saved)} missing={missing} → {CACHE}")


if __name__ == "__main__":
    main()
