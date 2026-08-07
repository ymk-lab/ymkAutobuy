#!/usr/bin/env python3
"""Emerging RS Wave inside SOXX universe (gate/RS vs SOXX; success vs SOXX B&H)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.data.loader import validate_ohlcv
from qresearch.strategy.emerging_rs_wave import EmergingRSWaveBook, GateId

OUT = ROOT / "examples" / "data" / "emerging_rs_wave_soxx"
CAPITAL = 50_000.0
START = pd.Timestamp("2025-01-01")
GATES: list[GateId] = ["G1", "G2", "G3", "G4"]

UNIVERSE = sorted(
    {
        "NVDA",
        "AVGO",
        "AMD",
        "AMAT",
        "QCOM",
        "TXN",
        "MU",
        "LRCX",
        "ADI",
        "KLAC",
        "INTC",
        "MRVL",
        "SNPS",
        "CDNS",
        "NXPI",
        "MCHP",
        "ASML",
        "TSM",
        "ON",
        "MPWR",
        "SWKS",
        "QRVO",
        "ENTG",
        "TER",
        "LSCC",
        "RMBS",
        "ACLS",
        "CRUS",
        "SLAB",
        "ALGM",
        "SYNA",
        "POWI",
        "DIOD",
        "SMTC",
        "FORM",
        "VECO",
        "UCTT",
        "COHU",
        "AMBA",
        "GFS",
        "ARM",
        "SMCI",
        "TSEM",
        "HIMX",
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


def fetch(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    try:
        raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    except Exception:
        return None
    return normalize(raw)


def fetch_many(tickers: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    try:
        raw = yf.download(
            tickers,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
        )
    except Exception:
        raw = None
    if raw is not None and not raw.empty and isinstance(raw.columns, pd.MultiIndex):
        level0 = raw.columns.get_level_values(0).unique()
        for sym in tickers:
            if sym not in level0:
                continue
            df = normalize(raw[sym].dropna(how="all"))
            if df is not None:
                out[sym] = df
    for sym in tickers:
        if sym in out:
            continue
        df = fetch(sym, start, end)
        if df is not None:
            out[sym] = df
    return out


def _active_weight(row: pd.Series) -> tuple[str | None, float]:
    active = row[row.abs() > 1e-12]
    if len(active) == 0:
        return None, 0.0
    return str(active.index[0]), float(active.iloc[0])


def simulate_book(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    decision_w: pd.DataFrame,
    capital: float,
    fees: FutuUsEquityFees,
) -> tuple[pd.Series, pd.DataFrame]:
    target = decision_w.shift(1).fillna(0.0)
    dates = list(target.index)
    eq = float(capital)
    equity: list[float] = []
    trades: list[dict] = []
    cur_sym: str | None = None
    cur_w = 0.0
    for i, dt in enumerate(dates):
        sym, w = _active_weight(target.loc[dt])
        ds = dt.strftime("%Y-%m-%d")
        if sym != cur_sym:
            if cur_sym is not None and cur_w != 0.0:
                px = float(opens.at[dt, cur_sym])
                notional = abs(cur_w) * eq
                cost = fees.total_cost_usd(notional, px)
                eq -= cost
                trades.append(
                    {
                        "date": ds,
                        "side": "SELL",
                        "symbol": cur_sym,
                        "weight_from": cur_w,
                        "weight_to": 0.0,
                        "price_open": round(px, 4),
                        "notional_usd": round(notional, 2),
                        "cost_usd": round(cost, 2),
                    }
                )
                cur_sym, cur_w = None, 0.0
            if sym is not None and w != 0.0:
                px = float(opens.at[dt, sym])
                notional = abs(w) * eq
                cost = fees.total_cost_usd(notional, px)
                eq -= cost
                trades.append(
                    {
                        "date": ds,
                        "side": "BUY",
                        "symbol": sym,
                        "weight_from": 0.0,
                        "weight_to": w,
                        "price_open": round(px, 4),
                        "notional_usd": round(notional, 2),
                        "cost_usd": round(cost, 2),
                    }
                )
                cur_sym, cur_w = sym, w
        elif abs(w - cur_w) > 1e-12:
            delta = w - cur_w
            if cur_sym is None:
                cur_sym = sym
            assert cur_sym is not None
            px = float(opens.at[dt, cur_sym])
            notional = abs(delta) * eq
            cost = fees.total_cost_usd(notional, px)
            eq -= cost
            trades.append(
                {
                    "date": ds,
                    "side": "BUY" if delta > 0 else "SELL",
                    "symbol": cur_sym,
                    "weight_from": cur_w,
                    "weight_to": w,
                    "price_open": round(px, 4),
                    "notional_usd": round(notional, 2),
                    "cost_usd": round(cost, 2),
                }
            )
            cur_w = w
            if cur_w == 0.0:
                cur_sym = None
        if cur_sym is not None and cur_w != 0.0:
            o = float(opens.at[dt, cur_sym])
            c = float(closes.at[dt, cur_sym])
            if i == 0:
                day_ret = cur_w * (c / o - 1.0)
            else:
                prev_c = float(closes.at[dates[i - 1], cur_sym])
                day_ret = (
                    cur_w * ((o / prev_c - 1.0) + (c / o - 1.0))
                    if np.isfinite(prev_c) and prev_c > 0
                    else cur_w * (c / o - 1.0)
                )
            eq *= 1.0 + day_ret
        for t in reversed(trades):
            if t["date"] != ds:
                break
            if t.get("equity_after_usd") is None:
                t["equity_after_usd"] = round(eq, 2)
        equity.append(eq)
    for t in trades:
        t.setdefault("equity_after_usd", None)
    return pd.Series(equity, index=target.index, name="equity"), pd.DataFrame(trades)


def metrics(eq: pd.Series, capital: float) -> dict:
    r = eq.pct_change().fillna(0.0)
    dd = float((eq / eq.cummax() - 1.0).min())
    mu, sd = float(r.mean()), float(r.std(ddof=0))
    ret = float(eq.iloc[-1] / capital - 1.0)
    return {
        "total_return": ret,
        "max_drawdown": dd,
        "sharpe": float((mu / sd) * np.sqrt(252)) if sd > 1e-12 else 0.0,
        "end_equity": float(eq.iloc[-1]),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fees = FutuUsEquityFees(slippage_bps=3.0)
    end = pd.Timestamp.today().normalize()
    end_fetch = (end + pd.Timedelta(days=3)).strftime("%Y-%m-%d")
    warm = "2023-01-01"

    print("Downloading SOXX + universe…")
    soxx = fetch("SOXX", warm, end_fetch)
    if soxx is None:
        raise SystemExit("SOXX download failed")
    soxx = soxx.loc[:end]
    frames = {s: df.loc[:end] for s, df in fetch_many(list(UNIVERSE), warm, end_fetch).items()}
    print(f"loaded {len(frames)}/{len(UNIVERSE)} names")

    idx = soxx.index
    closes = pd.DataFrame({s: frames[s]["close"].reindex(idx) for s in frames})
    opens = pd.DataFrame({s: frames[s]["open"].reindex(idx) for s in frames})
    keep = [c for c in closes.columns if closes[c].notna().sum() >= 220]
    closes, opens = closes[keep], opens[keep]
    print(f"usable symbols: {len(keep)}")

    win_idx = closes.loc[START:end].index
    rows = []
    for gate in GATES:
        book = EmergingRSWaveBook(gate=gate)
        decision, log = book.generate_weights(closes, soxx["close"])
        decision_w = decision.loc[win_idx]
        if len(log):
            log = log.copy()
            log["date"] = pd.to_datetime(log["date"])
            log_w = log[log["date"] >= START]
        else:
            log_w = log
        eq, trades = simulate_book(
            opens.loc[win_idx], closes.loc[win_idx], decision_w, CAPITAL, fees
        )
        m = metrics(eq, CAPITAL)
        m.update(
            {
                "gate": gate,
                "n_events": int(len(log_w)),
                "n_trades": int(len(trades)),
                "n_enters": int((log_w["action"] == "ENTER").sum()) if len(log_w) else 0,
            }
        )
        rows.append(m)
        eq.to_csv(OUT / f"equity_{gate.lower()}.csv", header=True)
        if len(trades):
            trades.to_csv(OUT / f"trades_{gate.lower()}.csv", index=False)
        if len(log_w):
            log_w.to_csv(OUT / f"events_{gate.lower()}.csv", index=False)
        print(
            f"{gate}: ret={m['total_return']:+.1%} dd={m['max_drawdown']:.1%} "
            f"enters={m['n_enters']}"
        )

    bh_decision = pd.DataFrame({"SOXX": 1.0}, index=win_idx)
    bh_eq, _ = simulate_book(
        soxx.loc[win_idx, ["open"]].rename(columns={"open": "SOXX"}),
        soxx.loc[win_idx, ["close"]].rename(columns={"close": "SOXX"}),
        bh_decision,
        CAPITAL,
        fees,
    )
    bh = metrics(bh_eq, CAPITAL)
    bh_eq.to_csv(OUT / "equity_soxx_bh.csv", header=True)
    print(f"SOXX_BH: ret={bh['total_return']:+.1%}")

    summary = pd.DataFrame(rows)
    summary["soxx_bh_return"] = bh["total_return"]
    summary["vs_soxx_pp"] = (summary["total_return"] - bh["total_return"]) * 100
    summary["beat_soxx"] = summary["total_return"] > bh["total_return"]
    summary = summary.sort_values("vs_soxx_pp", ascending=False)
    summary.to_csv(OUT / "summary.csv", index=False)
    cfg = {
        "strategy": "EmergingRSWaveBook",
        "benchmark": "SOXX",
        "symbols_used": keep,
        "gates": GATES,
        "capital_usd": CAPITAL,
        "window": [str(START.date()), str(win_idx.max().date())],
        "costs": "Futu+3bps next-bar flat-start",
        "soxx_bh": bh,
    }
    (OUT / "config.json").write_text(json.dumps(cfg, indent=2, default=float) + "\n")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
