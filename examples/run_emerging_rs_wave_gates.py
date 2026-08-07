#!/usr/bin/env python3
"""Emerging RS Wave book: Market Gate contest G1–G4 vs QQQ buy&hold."""

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

OUT = ROOT / "examples" / "data" / "emerging_rs_wave_gates"
CAPITAL = 50_000.0
START = pd.Timestamp("2025-01-01")
THR = 0.02
GATES: list[GateId] = ["G1", "G2", "G3", "G4"]

# Nasdaq-100 / QQQ-style research universe (static; missing tickers skipped)
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


def _normalize_ohlcv(raw: pd.DataFrame) -> pd.DataFrame | None:
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        # single-ticker multi-index from yfinance
        raw = raw.copy()
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw = raw.copy()
        raw.columns = [str(c).lower() for c in raw.columns]
    need = ["open", "high", "low", "close", "volume"]
    if any(c not in raw.columns for c in need):
        return None
    cleaned = raw[need].dropna()
    if cleaned.empty:
        return None
    # Drop rare bad prints instead of failing the whole symbol.
    ok = (
        (cleaned["high"] >= cleaned[["open", "close"]].max(axis=1))
        & (cleaned["low"] <= cleaned[["open", "close"]].min(axis=1))
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
    return _normalize_ohlcv(raw)


def fetch_many(tickers: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """Batch download; fall back per-ticker on failure."""
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
    if raw is not None and not raw.empty:
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = raw.columns.get_level_values(0).unique()
            for sym in tickers:
                if sym not in level0:
                    continue
                sub = raw[sym].dropna(how="all")
                try:
                    df = _normalize_ohlcv(sub)
                except ValueError:
                    df = None
                if df is not None and not df.empty:
                    out[sym] = df
        else:
            try:
                df = _normalize_ohlcv(raw)
            except ValueError:
                df = None
            if df is not None and len(tickers) == 1:
                out[tickers[0]] = df
    missing = [t for t in tickers if t not in out]
    for sym in missing:
        try:
            df = fetch(sym, start, end)
        except ValueError:
            df = None
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
    """Next-bar execution on open; at most one symbol with weight in {0,0.5,1}."""
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
                if np.isfinite(prev_c) and prev_c > 0 and np.isfinite(o) and o > 0:
                    day_ret = cur_w * ((o / prev_c - 1.0) + (c / o - 1.0))
                else:
                    day_ret = cur_w * (c / o - 1.0) if np.isfinite(o) and o > 0 else 0.0
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

    print("Downloading QQQ + universe…")
    qqq = fetch("QQQ", warm, end_fetch)
    if qqq is None or qqq.empty:
        raise SystemExit("QQQ download failed")
    qqq = qqq.loc[:end]

    frames = fetch_many(list(UNIVERSE), warm, end_fetch)
    frames = {s: df.loc[:end] for s, df in frames.items()}
    print(f"loaded {len(frames)}/{len(UNIVERSE)} names")

    idx = qqq.index
    closes = pd.DataFrame({s: frames[s]["close"].reindex(idx) for s in frames})
    opens = pd.DataFrame({s: frames[s]["open"].reindex(idx) for s in frames})
    min_bars = 220
    keep = [c for c in closes.columns if closes[c].notna().sum() >= min_bars]
    closes = closes[keep]
    opens = opens[keep]
    print(f"usable symbols: {len(keep)}")

    win_idx = closes.loc[START:end].index
    rows = []
    for gate in GATES:
        book = EmergingRSWaveBook(gate=gate)
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
            f"sharpe={m['sharpe']:.2f} enters={m['n_enters']} trades={m['n_trades']}"
        )

    # QQQ B&H on same window
    qqq_w = qqq.loc[win_idx]
    bh_decision = pd.DataFrame({"QQQ": 1.0}, index=qqq_w.index)
    bh_opens = qqq_w[["open"]].rename(columns={"open": "QQQ"})
    bh_closes = qqq_w[["close"]].rename(columns={"close": "QQQ"})
    bh_eq, bh_tr = simulate_book(bh_opens, bh_closes, bh_decision, CAPITAL, fees)
    bh = metrics(bh_eq, CAPITAL)
    bh_eq.to_csv(OUT / "equity_qqq_bh.csv", header=True)
    print(f"QQQ_BH: ret={bh['total_return']:+.1%} dd={bh['max_drawdown']:.1%}")

    summary = pd.DataFrame(rows)
    summary["bh_return"] = bh["total_return"]
    summary["vs_bh_pp"] = (summary["total_return"] - bh["total_return"]) * 100
    summary["beat_bh"] = summary["total_return"] > bh["total_return"]
    summary["bh_max_drawdown"] = bh["max_drawdown"]
    summary = summary.sort_values("vs_bh_pp", ascending=False)
    summary.to_csv(OUT / "summary.csv", index=False)

    cfg = {
        "strategy": "EmergingRSWaveBook",
        "gates": GATES,
        "universe_n_requested": len(UNIVERSE),
        "universe_n_used": len(keep),
        "symbols_used": keep,
        "capital_usd": CAPITAL,
        "window": [str(START.date()), str(win_idx.max().date())],
        "costs": "Futu+3bps thr2% next-bar flat-start",
        "rules": {
            "entry": "20d excess just turned + 3d persist + 10d excess>0 + 60d excess<=10%",
            "slot": "single name 100%, tie-break max 20d excess",
            "exit": "weaken/SMA50→half then flat; peakDD>=10% or gate_off→flat",
        },
        "qqq_bh": bh,
    }
    (OUT / "config.json").write_text(json.dumps(cfg, indent=2, default=float) + "\n")

    print("\n=== GATE CONTEST vs QQQ B&H ===")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
