#!/usr/bin/env python3
"""Scan QQQ universe with Emerging RS (G1) and print today's buy / hold action."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.data.loader import validate_ohlcv
from qresearch.strategy.emerging_rs_wave import (
    EmergingRSWaveBook,
    EmergingRSWaveConfig,
    market_gate,
)

OUT = ROOT / "examples" / "data" / "emerging_rs_wave_scan"
GATE = "G1"

UNIVERSE = sorted(
    {
        "AAPL",
        "ABNB",
        "ADBE",
        "ADI",
        "ADP",
        "ADSK",
        "AEP",
        "AMAT",
        "AMD",
        "AMGN",
        "AMZN",
        "APP",
        "ARM",
        "ASML",
        "AVGO",
        "AZN",
        "BIIB",
        "BKNG",
        "BKR",
        "CCEP",
        "CDNS",
        "CDW",
        "CEG",
        "CHTR",
        "CMCSA",
        "COST",
        "CPRT",
        "CRWD",
        "CSCO",
        "CSGP",
        "CSX",
        "CTAS",
        "CTSH",
        "DASH",
        "DDOG",
        "DLTR",
        "DXCM",
        "EA",
        "EXC",
        "FANG",
        "FAST",
        "FTNT",
        "GEHC",
        "GFS",
        "GILD",
        "GOOG",
        "GOOGL",
        "HON",
        "IDXX",
        "INTC",
        "INTU",
        "ISRG",
        "KDP",
        "KHC",
        "KLAC",
        "LIN",
        "LRCX",
        "LULU",
        "MAR",
        "MCHP",
        "MDB",
        "MDLZ",
        "MELI",
        "META",
        "MNST",
        "MRVL",
        "MSFT",
        "MU",
        "NFLX",
        "NVDA",
        "NXPI",
        "ODFL",
        "ON",
        "ORLY",
        "PANW",
        "PAYX",
        "PCAR",
        "PDD",
        "PEP",
        "PYPL",
        "QCOM",
        "REGN",
        "ROST",
        "SBUX",
        "SNPS",
        "TEAM",
        "TMUS",
        "TSLA",
        "TTD",
        "TTWO",
        "TXN",
        "VRSK",
        "VRTX",
        "WBD",
        "WDAY",
        "XEL",
        "ZS",
    }
)


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
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    end = (pd.Timestamp.today().normalize() + pd.Timedelta(days=3)).strftime("%Y-%m-%d")
    warm = "2023-01-01"

    qqq = normalize(yf.download("QQQ", start=warm, end=end, auto_adjust=True, progress=False))
    if qqq is None:
        raise SystemExit("QQQ download failed")

    raw = yf.download(
        list(UNIVERSE),
        start=warm,
        end=end,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    frames: dict[str, pd.DataFrame] = {}
    if isinstance(raw.columns, pd.MultiIndex):
        for sym in UNIVERSE:
            if sym not in raw.columns.get_level_values(0):
                continue
            df = normalize(raw[sym].dropna(how="all"))
            if df is not None:
                frames[sym] = df

    idx = qqq.index
    closes = pd.DataFrame({s: frames[s]["close"].reindex(idx) for s in frames})
    keep = [c for c in closes.columns if closes[c].notna().sum() >= 220]
    closes = closes[keep]

    cfg = EmergingRSWaveConfig()
    book = EmergingRSWaveBook(gate=GATE, config=cfg)
    weights, log = book.generate_weights(closes, qqq["close"])
    last = closes.index.max()
    gate_on = bool(market_gate(qqq["close"], GATE).loc[last])
    held = weights.loc[last]
    active = held[held.abs() > 1e-12]
    held_sym = str(active.index[0]) if len(active) else None
    held_w = float(active.iloc[0]) if len(active) else 0.0

    px = closes.astype(float)
    bench = qqq["close"].astype(float).reindex(px.index).ffill()
    ex20 = (px / px.shift(20) - 1.0).sub(bench / bench.shift(20) - 1.0, axis=0)
    ex10 = (px / px.shift(10) - 1.0).sub(bench / bench.shift(10) - 1.0, axis=0)
    ex60 = (px / px.shift(60) - 1.0).sub(bench / bench.shift(60) - 1.0, axis=0)
    pos = ex20 > 0
    persist = pos & pos.shift(1).fillna(False) & pos.shift(2).fillna(False)
    just = persist & pos.shift(3).eq(False)
    entry_ok = just & (ex10 > 0) & (ex60 <= cfg.already_strong_cap)

    rows = []
    for s in keep:
        if bool(entry_ok.at[last, s]):
            rows.append(
                {
                    "symbol": s,
                    "excess_20": float(ex20.at[last, s]),
                    "excess_10": float(ex10.at[last, s]),
                    "excess_60": float(ex60.at[last, s]),
                    "close": float(px.at[last, s]),
                }
            )
    cands = pd.DataFrame(rows).sort_values("excess_20", ascending=False) if rows else pd.DataFrame()

    if held_sym is not None:
        action = "HOLD"
        pick = held_sym
        reason = f"席位已佔用：繼續持有 {held_sym} {held_w:.0%}；今日新訊號不開第二檔"
    elif not gate_on:
        action = "FLAT"
        pick = None
        reason = "G1 閘門關閉，不買入"
    elif cands.empty:
        action = "FLAT"
        pick = None
        reason = "閘門開著但無剛轉強標的"
    else:
        action = "BUY"
        pick = str(cands.iloc[0]["symbol"])
        reason = f"買入唯一席位：{pick} 100%（20d 超額最高）"

    result = {
        "asof": str(last.date()),
        "gate": GATE,
        "gate_open": gate_on,
        "action": action,
        "buy_or_hold": pick,
        "slot_weight": held_w,
        "reason": reason,
        "candidates": cands.to_dict(orient="records") if len(cands) else [],
    }
    (OUT / "latest_scan.json").write_text(json.dumps(result, indent=2) + "\n")
    if len(cands):
        cands.to_csv(OUT / "candidates.csv", index=False)
    if len(log):
        log.tail(20).to_csv(OUT / "recent_events.csv", index=False)

    print(f"asof={last.date()} gate={GATE} open={gate_on}")
    print(f"action={action} symbol={pick} weight={held_w if held_sym else (1.0 if action=='BUY' else 0.0)}")
    print(reason)
    print("candidates:")
    print(cands.to_string(index=False) if len(cands) else "(none)")


if __name__ == "__main__":
    main()
