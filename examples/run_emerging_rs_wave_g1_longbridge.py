#!/usr/bin/env python3
"""Emerging RS Wave G1 on Longbridge daily bars (QQQ universe) vs QQQ B&H."""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.brokers.longbridge.config import has_longbridge_credentials, load_longbridge_config
from qresearch.brokers.longbridge.history import candlesticks_to_ohlcv
from qresearch.data.loader import validate_ohlcv
from qresearch.strategy.emerging_rs_wave import EmergingRSWaveBook

# Reuse simulation helpers from the yfinance gate contest runner.
from run_emerging_rs_wave_gates import (  # type: ignore
    CAPITAL,
    START,
    THR,
    UNIVERSE,
    metrics,
    simulate_book,
)

OUT = ROOT / "examples" / "data" / "emerging_rs_wave_qqq_g1_longbridge"
CACHE = OUT / "cache_ohlcv"
WARM_START = date(2023, 1, 1)
END = date(2026, 8, 7)
GATE = "G1"
MIN_BARS = 220
SLEEP_SEC = 0.05
RETRIES = 3


def _normalize_cached(df: pd.DataFrame) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    raw = df.copy()
    raw.columns = [str(c).lower() for c in raw.columns]
    need = ["open", "high", "low", "close", "volume"]
    if any(c not in raw.columns for c in need):
        return None
    cleaned = raw[need].dropna()
    if cleaned.empty:
        return None
    try:
        out = validate_ohlcv(cleaned)
    except ValueError:
        return None
    out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
    return out[~out.index.duplicated(keep="last")].sort_index()


def load_cache(symbol: str) -> pd.DataFrame | None:
    path = CACHE / f"{symbol}.csv"
    if not path.is_file() or path.stat().st_size < 64:
        return None
    try:
        raw = pd.read_csv(path, index_col=0, parse_dates=True)
    except Exception:
        return None
    df = _normalize_cached(raw)
    if df is None or len(df) < MIN_BARS:
        return None
    return df


def save_cache(symbol: str, df: pd.DataFrame) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out.index.name = "datetime"
    out.to_csv(CACHE / f"{symbol}.csv")


def fetch_symbol(quote_ctx, symbol: str) -> pd.DataFrame | None:
    from longbridge.openapi import AdjustType, Period

    lb_sym = f"{symbol}.US"
    last_err: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            candles = list(
                quote_ctx.history_candlesticks_by_date(
                    lb_sym,
                    Period.Day,
                    AdjustType.ForwardAdjust,
                    WARM_START,
                    END,
                )
            )
            if not candles:
                return None
            df = candlesticks_to_ohlcv(candles)
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            return df
        except Exception as exc:  # noqa: BLE001 — venue/network noise
            last_err = exc
            time.sleep(0.4 * attempt)
    print(f"  fail {symbol}: {last_err}")
    return None


def load_panel(symbols: list[str]) -> dict[str, pd.DataFrame]:
    if not has_longbridge_credentials():
        raise SystemExit("Missing Longbridge credentials in env / .env")

    from longbridge.openapi import QuoteContext

    quote_ctx = QuoteContext(load_longbridge_config())
    frames: dict[str, pd.DataFrame] = {}
    try:
        for i, sym in enumerate(symbols, 1):
            cached = load_cache(sym)
            if cached is not None:
                frames[sym] = cached
                print(f"[{i}/{len(symbols)}] cache {sym}: {len(cached)} bars")
                continue
            df = fetch_symbol(quote_ctx, sym)
            if df is not None and not df.empty:
                save_cache(sym, df)
                frames[sym] = df
                print(f"[{i}/{len(symbols)}] fetch {sym}: {len(df)} bars")
            else:
                print(f"[{i}/{len(symbols)}] skip {sym}")
            time.sleep(SLEEP_SEC)
    finally:
        try:
            quote_ctx.close()
        except Exception:
            pass
    return frames


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    fees = FutuUsEquityFees(slippage_bps=3.0)

    want = ["QQQ", *list(UNIVERSE)]
    print(f"Loading Longbridge daily bars for {len(want)} symbols…")
    frames = load_panel(want)
    if "QQQ" not in frames:
        raise SystemExit("QQQ history failed")

    qqq = frames["QQQ"]
    end_ts = pd.Timestamp(END)
    qqq = qqq.loc[:end_ts]
    stock_frames = {s: df.loc[:end_ts] for s, df in frames.items() if s != "QQQ"}
    print(f"loaded {len(stock_frames)}/{len(UNIVERSE)} names (+QQQ)")

    idx = qqq.index
    closes = pd.DataFrame({s: stock_frames[s]["close"].reindex(idx) for s in stock_frames})
    opens = pd.DataFrame({s: stock_frames[s]["open"].reindex(idx) for s in stock_frames})
    keep = [c for c in closes.columns if closes[c].notna().sum() >= MIN_BARS]
    closes = closes[keep]
    opens = opens[keep]
    print(f"usable symbols: {len(keep)}")

    win_idx = closes.loc[START:end_ts].index
    book = EmergingRSWaveBook(gate=GATE)
    decision, log = book.generate_weights(closes, qqq["close"])
    decision_w = decision.loc[win_idx]
    if len(log):
        log = log.copy()
        log["date"] = pd.to_datetime(log["date"])
        log_w = log[log["date"] >= START]
    else:
        log_w = log

    eq, trades = simulate_book(
        opens.loc[win_idx],
        closes.loc[win_idx],
        decision_w,
        CAPITAL,
        fees,
    )
    m = metrics(eq, CAPITAL)
    m.update(
        {
            "gate": GATE,
            "n_events": int(len(log_w)),
            "n_trades": int(len(trades)),
            "n_enters": int((log_w["action"] == "ENTER").sum()) if len(log_w) else 0,
            "data_source": "longbridge",
        }
    )

    qqq_w = qqq.loc[win_idx]
    bh_decision = pd.DataFrame({"QQQ": 1.0}, index=qqq_w.index)
    bh_opens = qqq_w[["open"]].rename(columns={"open": "QQQ"})
    bh_closes = qqq_w[["close"]].rename(columns={"close": "QQQ"})
    bh_eq, _bh_tr = simulate_book(bh_opens, bh_closes, bh_decision, CAPITAL, fees)
    bh = metrics(bh_eq, CAPITAL)

    eq.to_csv(OUT / "equity_g1.csv", header=True)
    bh_eq.to_csv(OUT / "equity_qqq_bh.csv", header=True)
    if len(trades):
        trades.to_csv(OUT / "trades_g1.csv", index=False)
    if len(log_w):
        log_w.to_csv(OUT / "events_g1.csv", index=False)

    summary = {
        **m,
        "bh_return": bh["total_return"],
        "bh_max_drawdown": bh["max_drawdown"],
        "bh_sharpe": bh["sharpe"],
        "bh_end_equity": bh["end_equity"],
        "vs_bh_pp": (m["total_return"] - bh["total_return"]) * 100,
        "beat_bh": bool(m["total_return"] > bh["total_return"]),
        "trade_threshold": THR,
        "window": [str(START.date()), str(win_idx.max().date())],
        "universe_n_used": len(keep),
        "symbols_used": keep,
        "capital_usd": CAPITAL,
        "costs": "Futu HK US fixed + 3bps slip; next-bar open; thr2%; flat-start",
        "adjust": "ForwardAdjust",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float) + "\n")
    pd.DataFrame([{k: summary[k] for k in (
        "gate", "total_return", "max_drawdown", "sharpe", "end_equity",
        "bh_return", "bh_max_drawdown", "vs_bh_pp", "beat_bh",
        "n_enters", "n_trades", "universe_n_used",
    )}]).to_csv(OUT / "summary.csv", index=False)

    print(
        f"\nG1 (Longbridge): ret={m['total_return']:+.1%} dd={m['max_drawdown']:.1%} "
        f"sharpe={m['sharpe']:.2f} enters={m['n_enters']} trades={m['n_trades']}"
    )
    print(f"QQQ_BH: ret={bh['total_return']:+.1%} dd={bh['max_drawdown']:.1%}")
    print(f"vs QQQ: {summary['vs_bh_pp']:+.1f} pp | beat={summary['beat_bh']}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
