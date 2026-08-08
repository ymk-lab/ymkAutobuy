#!/usr/bin/env python3
"""Fetch OHLCV caches for Structure Gate expansion books.

Books:
  IWM  — bench IWM; universe = SPSM (S&P 600) holdings as liquid small-cap proxy
  XLF / XLK / XLE / XBI — bench + SSGA daily holdings
"""

from __future__ import annotations

import sys
import urllib.request
from io import BytesIO
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.data.loader import validate_ohlcv

DATA = ROOT / "examples" / "data"
START, END = "2023-01-01", "2026-08-10"
UA = {"User-Agent": "Mozilla/5.0"}


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


def ssga_tickers(sym: str) -> list[str]:
    url = (
        "https://www.ssga.com/library-content/products/fund-data/etfs/us/"
        f"holdings-daily-us-en-{sym.lower()}.xlsx"
    )
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    df = pd.read_excel(BytesIO(data), header=None)
    hdr = None
    for i in range(min(40, len(df))):
        row = [str(x).strip().lower() for x in df.iloc[i].tolist()]
        if "ticker" in row:
            hdr = i
            break
    if hdr is None:
        raise SystemExit(f"{sym}: no Ticker header in SSGA sheet")
    body = df.iloc[hdr + 1 :].copy()
    body.columns = [str(c).strip() for c in df.iloc[hdr].tolist()]
    tcol = next(c for c in body.columns if c.lower() == "ticker")
    out: list[str] = []
    seen: set[str] = set()
    for t in body[tcol].dropna().astype(str):
        t = t.strip().upper().replace(".", "-")
        if not t or t in seen or " " in t or t.startswith("CASH"):
            continue
        if not t.replace("-", "").isalnum():
            continue
        if len(t) > 6:
            continue
        # Drop index futures / month codes leaked into SSGA sheets (e.g. RTYU6).
        if t[-1].isdigit():
            continue
        seen.add(t)
        out.append(t)
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
        level0 = set(raw.columns.get_level_values(0).unique())
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
    print(f"\n=== {name} bench={bench} members={len(members)} download={len(tickers)} ===")
    panel = download_panel(tickers)
    if bench not in panel:
        raise SystemExit(f"{name}: bench {bench} download failed")
    saved = []
    for sym, df in panel.items():
        df.to_csv(cache / f"{sym}.csv")
        saved.append(sym)
    usable = sorted(s for s in saved if s != bench)
    (out_dir / "universe.txt").write_text(
        f"# {note}\n" + "\n".join(usable) + "\n"
    )
    print(f"saved_bench=1 usable_members={len(usable)} missing_bench_ok={bench in saved}")


def main() -> None:
    books = [
        (
            "IWM",
            "IWM",
            ssga_tickers("spsm"),
            "IWM Structure Gate; universe = SPSM (S&P 600) liquid small-cap proxy",
        ),
        ("XLF", "XLF", ssga_tickers("xlf"), "XLF Financial Select Sector holdings"),
        ("XLK", "XLK", ssga_tickers("xlk"), "XLK Technology Select Sector holdings"),
        ("XLE", "XLE", ssga_tickers("xle"), "XLE Energy Select Sector holdings"),
        ("XBI", "XBI", ssga_tickers("xbi"), "XBI SPDR S&P Biotech holdings"),
    ]
    only = [a.strip().upper() for a in sys.argv[1:]]
    for name, bench, members, note in books:
        if only and name not in only:
            continue
        write_book(name, bench, members, note)
    print("\nDone.")


if __name__ == "__main__":
    main()
