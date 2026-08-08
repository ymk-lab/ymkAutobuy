#!/usr/bin/env python3
"""Fetch Hang Seng (HSI) and Hang Seng TECH (HSTECH) panels for Structure Gate.

Benchmarks:
  HSI    → 2800.HK (Tracker Fund of Hong Kong)
  HSTECH → 3067.HK (iShares Hang Seng TECH ETF)
"""

from __future__ import annotations

import re
import sys
import urllib.request
from io import StringIO
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.data.loader import validate_ohlcv

DATA = ROOT / "examples" / "data"
START, END = "2023-01-01", "2026-08-10"
UA = {"User-Agent": "Mozilla/5.0 (qresearch)"}

# Hang Seng TECH — scrape + known members (SEHK codes).
HSTECH_EXTRA = [
    "0700",
    "9988",
    "3690",
    "1810",
    "9618",
    "9888",
    "1024",
    "9999",
    "1211",
    "0981",
    "2015",
    "9866",
    "9868",
    "9626",
    "9961",
    "0992",
    "2382",
    "6618",
    "0241",
    "0020",
    "1347",
    "0300",
    "6690",
    "9660",
    "9863",
    "2018",
    "0268",
    "3888",
    "0772",
    "6060",
    "9626",
    "9999",
]


def to_hk(code: str | int) -> str:
    return f"{int(str(code).strip()):04d}.HK"


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


def hsi_universe() -> list[str]:
    req = urllib.request.Request(
        "https://en.wikipedia.org/wiki/Hang_Seng_Index", headers=UA
    )
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")
    tables = pd.read_html(StringIO(html))
    table = next(t for t in tables if "Ticker" in [str(c) for c in t.columns])
    out: list[str] = []
    seen: set[str] = set()
    for x in table["Ticker"].astype(str):
        m = re.search(r"(\d{1,5})", x.replace(",", ""))
        if not m:
            continue
        sym = to_hk(m.group(1))
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def hstech_universe() -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    try:
        req = urllib.request.Request(
            "https://stockanalysis.com/quote/hkg/3067/holdings/", headers=UA
        )
        html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")
        codes = re.findall(r"/quote/hkg/(\d{1,5})/", html, flags=re.I)
        codes += re.findall(r"HKG:\s*(\d{1,5})", html)
        for c in codes:
            sym = to_hk(c)
            if sym in seen or sym == "3067.HK":
                continue
            seen.add(sym)
            out.append(sym)
    except Exception as exc:
        print("HSTECH scrape warning:", exc)
    for c in HSTECH_EXTRA:
        sym = to_hk(c)
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def download_panel(tickers: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    raw = yf.download(
        tickers,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if raw is not None and not raw.empty and isinstance(raw.columns, pd.MultiIndex):
        level0 = set(map(str, raw.columns.get_level_values(0).unique()))
        for sym in tickers:
            if sym not in level0:
                continue
            df = normalize(raw[sym].dropna(how="all"))
            if df is not None and len(df) >= 220:
                out[sym] = df
    missing = [t for t in tickers if t not in out]
    for sym in missing:
        try:
            r = yf.download(sym, start=START, end=END, auto_adjust=True, progress=False)
        except Exception:
            continue
        df = normalize(r)
        if df is not None and len(df) >= 220:
            out[sym] = df
    return out


def write_book(name: str, bench: str, members: list[str], note: str) -> None:
    out_dir = DATA / f"emerging_rs_wave_{name.lower()}"
    cache = out_dir / "cache_ohlcv"
    cache.mkdir(parents=True, exist_ok=True)
    tickers = [bench] + [m for m in members if m != bench]
    print(f"\n=== {name} bench={bench} members={len(members)} ===", flush=True)
    panel = download_panel(tickers)
    if bench not in panel:
        raise SystemExit(f"{name}: bench {bench} download failed")
    for sym, df in panel.items():
        df.to_csv(cache / f"{sym}.csv")
    usable = sorted(s for s in panel if s != bench)
    (out_dir / "universe.txt").write_text(f"# {note}\n" + "\n".join(usable) + "\n")
    print(f"saved usable_members={len(usable)} missing={[t for t in tickers if t not in panel][:12]}")


def main() -> None:
    only = [a.strip().upper() for a in sys.argv[1:]]
    books = [
        ("HSI", "2800.HK", hsi_universe(), "HSI Structure Gate; bench=2800.HK Tracker Fund"),
        (
            "HSTECH",
            "3067.HK",
            hstech_universe(),
            "HSTECH Structure Gate; bench=3067.HK iShares Hang Seng TECH",
        ),
    ]
    for name, bench, members, note in books:
        if only and name not in only:
            continue
        write_book(name, bench, members, note)
    print("\nDone.")


if __name__ == "__main__":
    main()
