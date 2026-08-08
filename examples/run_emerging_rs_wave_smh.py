#!/usr/bin/env python3
"""Emerging RS on SMH semiconductor book: G1 full + 2x$25k multi vs SMH B&H."""

from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta
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
from qresearch.strategy.emerging_rs_multi_slot import EmergingRSMultiSlotConfig, simulate_multi_slot
from qresearch.strategy.emerging_rs_wave import EmergingRSWaveBook
from run_emerging_rs_wave_gates import metrics, simulate_book  # type: ignore
from run_emerging_rs_wave_soxx import UNIVERSE  # type: ignore

OUT = ROOT / "examples" / "data" / "emerging_rs_wave_smh"
CACHE = OUT / "cache_ohlcv"
CAPITAL = 50_000.0
START = pd.Timestamp("2025-01-01")
END = date(2026, 8, 7)
WARM = date(2023, 1, 1)
MIN_BARS = 220


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[~df.index.duplicated(keep="last")].sort_index()


def load_cache(sym: str) -> pd.DataFrame | None:
    p = CACHE / f"{sym}.csv"
    if not p.is_file() or p.stat().st_size < 64:
        return None
    raw = pd.read_csv(p, index_col=0, parse_dates=True)
    raw.columns = [str(c).lower() for c in raw.columns]
    try:
        df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
    except ValueError:
        return None
    return _norm(df)


def save_cache(sym: str, df: pd.DataFrame) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out.index.name = "datetime"
    out.to_csv(CACHE / f"{sym}.csv")


def fetch_lb(quote_ctx, sym: str) -> pd.DataFrame | None:
    from longbridge.openapi import AdjustType, Period

    for attempt in range(1, 4):
        try:
            candles = list(
                quote_ctx.history_candlesticks_by_date(
                    f"{sym}.US",
                    Period.Day,
                    AdjustType.ForwardAdjust,
                    WARM,
                    END + timedelta(days=1),
                )
            )
            if not candles:
                return None
            return _norm(candlesticks_to_ohlcv(candles))
        except Exception as exc:  # noqa: BLE001
            if attempt == 3:
                print(f"  fail {sym}: {exc}")
            time.sleep(0.3 * attempt)
    return None


def load_panel(symbols: list[str]) -> dict[str, pd.DataFrame]:
    if not has_longbridge_credentials():
        raise SystemExit("Need Longbridge credentials")
    from longbridge.openapi import QuoteContext

    qc = QuoteContext(load_longbridge_config())
    frames: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols, 1):
        cached = load_cache(sym)
        if cached is not None and len(cached) >= MIN_BARS:
            frames[sym] = cached.loc[: pd.Timestamp(END)]
            if sym == "SMH" or len(frames) % 15 == 0:
                print(f"cache {sym} {len(cached)}")
            continue
        df = fetch_lb(qc, sym)
        if df is not None and len(df) >= MIN_BARS:
            save_cache(sym, df)
            frames[sym] = df.loc[: pd.Timestamp(END)]
            if i == 1 or i % 15 == 0 or i == len(symbols):
                print(f"[{i}/{len(symbols)}] {sym} {len(df)}")
        else:
            print(f"[{i}/{len(symbols)}] skip {sym}")
        time.sleep(0.05)
    return frames


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    fees = FutuUsEquityFees(slippage_bps=3.0)
    want = ["SMH", *list(UNIVERSE)]
    print(f"Loading Longbridge SMH + {len(UNIVERSE)} semis…")
    frames = load_panel(want)
    if "SMH" not in frames:
        raise SystemExit("SMH failed")
    smh = frames["SMH"]
    stock = {s: df for s, df in frames.items() if s != "SMH"}
    print(f"loaded {len(stock)} names + SMH")

    idx = smh.index
    closes = pd.DataFrame({s: stock[s]["close"].reindex(idx) for s in stock})
    opens = pd.DataFrame({s: stock[s]["open"].reindex(idx) for s in stock})
    keep = [c for c in closes.columns if closes[c].notna().sum() >= MIN_BARS]
    closes, opens = closes[keep], opens[keep]
    print(f"usable={len(keep)}")

    win_idx = closes.loc[START : pd.Timestamp(END)].index
    rows = []

    # --- Full G1 single-slot 100% ---
    book = EmergingRSWaveBook(gate="G1")
    decision, log = book.generate_weights(closes, smh["close"])
    decision_w = decision.loc[win_idx]
    log_w = log.copy()
    if len(log_w):
        log_w["date"] = pd.to_datetime(log_w["date"])
        log_w = log_w[log_w["date"] >= START]
    eq, trades = simulate_book(opens.loc[win_idx], closes.loc[win_idx], decision_w, CAPITAL, fees)
    m = metrics(eq, CAPITAL)
    m.update(
        {
            "variant": "G1_full_100pct",
            "n_trades": int(len(trades)),
            "n_enters": int((log_w["action"] == "ENTER").sum()) if len(log_w) else 0,
        }
    )
    rows.append(m)
    eq.to_csv(OUT / "equity_g1_full.csv", header=True)
    if len(trades):
        trades.to_csv(OUT / "trades_g1_full.csv", index=False)
    if len(log_w):
        log_w.to_csv(OUT / "events_g1_full.csv", index=False)
    print(
        f"G1_full: ret={m['total_return']:+.1%} dd={m['max_drawdown']:.1%} "
        f"sharpe={m['sharpe']:.2f} enters={m['n_enters']}"
    )

    # --- Multi 2 x $25k ---
    cfg = EmergingRSMultiSlotConfig(max_names=2, max_notional_usd=25_000.0)
    multi = simulate_multi_slot(
        opens,
        closes,
        smh["close"],
        capital=CAPITAL,
        gate="G1",
        config=cfg,
        fees=fees,
        start=START,
    )
    mm = metrics(multi.equity, CAPITAL)
    mm.update(
        {
            "variant": "G1_multi_2x25k",
            "n_trades": int(len(multi.trades)),
            "n_enters": int((multi.events["action"] == "ENTER").sum()) if len(multi.events) else 0,
            "max_concurrent": int(multi.holdings_count.max()) if len(multi.holdings_count) else 0,
            "avg_concurrent": float(multi.holdings_count.mean()) if len(multi.holdings_count) else 0.0,
        }
    )
    rows.append(mm)
    multi.equity.to_csv(OUT / "equity_g1_2x25k.csv", header=True)
    if len(multi.trades):
        multi.trades.to_csv(OUT / "trades_g1_2x25k.csv", index=False)
    if len(multi.events):
        multi.events.to_csv(OUT / "events_g1_2x25k.csv", index=False)
    print(
        f"G1_2x25k: ret={mm['total_return']:+.1%} dd={mm['max_drawdown']:.1%} "
        f"sharpe={mm['sharpe']:.2f} avg_hold={mm['avg_concurrent']:.1f}"
    )

    # SMH B&H
    smh_w = smh.loc[win_idx]
    bh_decision = pd.DataFrame({"SMH": 1.0}, index=smh_w.index)
    bh_eq, _ = simulate_book(
        smh_w[["open"]].rename(columns={"open": "SMH"}),
        smh_w[["close"]].rename(columns={"close": "SMH"}),
        bh_decision,
        CAPITAL,
        fees,
    )
    bh = metrics(bh_eq, CAPITAL)
    bh_eq.to_csv(OUT / "equity_smh_bh.csv", header=True)
    print(f"SMH_BH: ret={bh['total_return']:+.1%} dd={bh['max_drawdown']:.1%}")

    summary = pd.DataFrame(rows)
    summary["bh_return"] = bh["total_return"]
    summary["bh_max_drawdown"] = bh["max_drawdown"]
    summary["vs_bh_pp"] = (summary["total_return"] - bh["total_return"]) * 100
    summary["beat_bh"] = summary["total_return"] > bh["total_return"]
    summary.to_csv(OUT / "summary.csv", index=False)
    cfg_out = {
        "benchmark": "SMH",
        "universe": "SOXX-style semiconductor names",
        "universe_n_used": len(keep),
        "symbols_used": keep,
        "capital_usd": CAPITAL,
        "window": [str(START.date()), str(win_idx.max().date())],
        "variants": ["G1_full_100pct", "G1_multi_2x25k"],
        "smh_bh": bh,
        "results": summary.to_dict(orient="records"),
    }
    (OUT / "summary.json").write_text(json.dumps(cfg_out, indent=2, default=float) + "\n")
    print("\n=== vs SMH B&H ===")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
