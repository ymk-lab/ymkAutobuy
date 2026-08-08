#!/usr/bin/env python3
"""Run Structure Gate v8 and write trade ledger + monthly P&L."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.strategy.structure_gate import StructureGateConfig
from run_structure_gate_bakeoff import BOOKS, CAPITAL, run_book  # type: ignore


def monthly_pnl(equity: pd.Series, capital: float) -> pd.DataFrame:
    eq = equity.astype(float).sort_index()
    # month-end marks; include first point as prior for first month return
    me = eq.resample("ME").last().dropna()
    if len(me) == 0:
        return pd.DataFrame()
    prev = eq.iloc[0]
    rows = []
    for dt, val in me.items():
        pnl = float(val - prev)
        ret = float(val / prev - 1.0) if prev else 0.0
        rows.append(
            {
                "month": pd.Timestamp(dt).strftime("%Y-%m"),
                "end_equity": round(float(val), 2),
                "pnl_usd": round(pnl, 2),
                "return": ret,
                "return_pct": round(ret * 100, 2),
            }
        )
        prev = float(val)
    out = pd.DataFrame(rows)
    out["cum_pnl_usd"] = (out["end_equity"] - capital).round(2)
    return out


def enrich_trades(trades: pd.DataFrame, modes: pd.Series, bench: str) -> pd.DataFrame:
    if trades is None or len(trades) == 0:
        return pd.DataFrame(
            columns=[
                "date",
                "side",
                "symbol",
                "bench_etf",
                "shares",
                "price",
                "notional_usd",
                "cost_usd",
                "reason",
                "mode",
            ]
        )
    t = trades.copy()
    t["date"] = pd.to_datetime(t["date"])
    mode_map = modes.copy()
    mode_map.index = pd.to_datetime(mode_map.index).normalize()
    t["mode"] = t["date"].dt.normalize().map(mode_map)
    t["bench_etf"] = bench
    t["symbol_resolved"] = t["symbol"].where(t["symbol"] != "BENCH", bench)
    t["date"] = t["date"].dt.strftime("%Y-%m-%d")
    cols = [
        "date",
        "side",
        "symbol",
        "symbol_resolved",
        "bench_etf",
        "shares",
        "price",
        "notional_usd",
        "cost_usd",
        "reason",
        "mode",
    ]
    return t[cols]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("books", nargs="*", default=["SPY", "QQQ", "SMH", "SOXX"])
    ap.add_argument("--start", default="2025-08-01")
    ap.add_argument("--end", default="2026-08-07")
    ap.add_argument(
        "--out",
        default=str(ROOT / "examples/data/structure_gate_ledger_2025_08_2026_08"),
    )
    args = ap.parse_args()

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    fees = FutuUsEquityFees(slippage_bps=3.0)
    cfg = StructureGateConfig()
    books = [b.strip().upper() for b in args.books]
    all_trades: list[pd.DataFrame] = []
    all_monthly: list[pd.DataFrame] = []
    summaries: dict = {
        "rule": "structure_gate_v8",
        "window": [str(start.date()), str(end.date())],
        "capital_usd": CAPITAL,
        "fee_model": "futu_us + 3bps slip",
        "books": {},
    }

    for book in books:
        print(f"\n##### LEDGER {book} #####")
        rep = run_book(
            book, fees, cfg, start=start, end=end, out_root=out_root
        )
        book_dir = out_root / book.lower()
        eq = pd.read_csv(
            book_dir / "equity_structure_gate.csv", index_col=0, parse_dates=True
        ).iloc[:, 0]
        modes = pd.read_csv(book_dir / "modes.csv", index_col=0, parse_dates=True).iloc[
            :, 0
        ]
        trades_path = book_dir / "trades.csv"
        trades = (
            pd.read_csv(trades_path)
            if trades_path.is_file()
            else pd.DataFrame()
        )
        bench = BOOKS[book]["bench"]
        ledger = enrich_trades(trades, modes, bench)
        monthly = monthly_pnl(eq, CAPITAL)
        monthly.insert(0, "book", book)

        ledger_path = book_dir / "trades_ledger.csv"
        monthly_path = book_dir / "monthly_pnl.csv"
        ledger.to_csv(ledger_path, index=False)
        monthly.to_csv(monthly_path, index=False)
        # JSON copies (csv is gitignored in this repo)
        (book_dir / "trades_ledger.json").write_text(
            ledger.to_json(orient="records", indent=2) + "\n"
        )
        (book_dir / "monthly_pnl.json").write_text(
            monthly.to_json(orient="records", indent=2) + "\n"
        )

        ledger2 = ledger.copy()
        ledger2.insert(0, "book", book)
        all_trades.append(ledger2)
        all_monthly.append(monthly)

        summaries["books"][book] = {
            **{k: rep[k] for k in ("soft_pass", "hard_pass_beat_both", "vs_bh_pp", "vs_ers_pp")},
            "structure_gate": rep["structure_gate"],
            "bench_bh": rep["bench_bh"],
            "n_trades": int(len(ledger)),
            "trade_costs_usd": float(ledger["cost_usd"].sum()) if len(ledger) else 0.0,
            "monthly": monthly.to_dict(orient="records"),
            "trades": ledger.to_dict(orient="records"),
        }
        print(f"trades={len(ledger)} monthly_rows={len(monthly)}")
        print(monthly.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    if all_trades:
        cat_t = pd.concat(all_trades, ignore_index=True)
        cat_t.to_csv(out_root / "all_trades_ledger.csv", index=False)
        (out_root / "all_trades_ledger.json").write_text(
            cat_t.to_json(orient="records", indent=2) + "\n"
        )
    if all_monthly:
        cat_m = pd.concat(all_monthly, ignore_index=True)
        cat_m.to_csv(out_root / "all_monthly_pnl.csv", index=False)
        (out_root / "all_monthly_pnl.json").write_text(
            cat_m.to_json(orient="records", indent=2) + "\n"
        )
    (out_root / "ledger_summary.json").write_text(
        json.dumps(summaries, indent=2, default=float) + "\n"
    )
    print(f"\nwrote {out_root}")


if __name__ == "__main__":
    main()
