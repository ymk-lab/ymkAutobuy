#!/usr/bin/env python3
"""Backtest PYPL.US over the trailing ~6 months (Yahoo Finance)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from qresearch.backtest.costs import CostModel
from qresearch.backtest.engine import BacktestEngine
from qresearch.data.loader import load_ohlcv_csv, save_ohlcv_csv, validate_ohlcv
from qresearch.strategy.base import Strategy
from qresearch.strategy.examples import RegimeAwareTrendStrategy, SMACrossoverStrategy
from qresearch.validation.param_search import walk_forward_grid_search


class BuyAndHold(Strategy):
    name = "buy_hold"

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=data.index, name="signal")


def fetch_pypl(start: datetime, end: datetime) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(
        "PYPL",
        start=start.date().isoformat(),
        end=end.date().isoformat(),
        auto_adjust=True,
        progress=False,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [str(c).lower() for c in raw.columns]
    return validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())


def main() -> None:
    csv_path = ROOT / "examples" / "data" / "PYPL_US_6m.csv"
    end = datetime.now(UTC)
    start = end - timedelta(days=186)

    if csv_path.exists():
        data = load_ohlcv_csv(csv_path)
        print(f"Loaded cache {csv_path} ({len(data)} bars)")
    else:
        print(f"Fetching PYPL {start.date()} → {end.date()}")
        data = fetch_pypl(start, end)
        save_ohlcv_csv(data, csv_path)
        print(f"Saved {csv_path}")

    print(f"Range: {data.index[0].date()} → {data.index[-1].date()}  bars={len(data)}")

    engine = BacktestEngine(
        initial_capital=100_000,
        cost_model=CostModel(fee_bps=1.0, slippage_bps=3.0),
        allow_short=False,
    )
    results = {
        "buy_hold": engine.run(data, BuyAndHold()),
        "sma_10_30": engine.run(data, SMACrossoverStrategy(fast=10, slow=30)),
        "regime_trend": engine.run(
            data, RegimeAwareTrendStrategy(fast=10, slow=40, high_vol_weight=0.0)
        ),
    }
    cmp = pd.DataFrame({k: v.stats for k, v in results.items()}).T
    print("\n=== In-sample (costed) ===")
    print(cmp.round(4).to_string())

    n = len(data)
    train, test = max(60, n // 2), max(15, n // 8)

    def builder(params: dict) -> RegimeAwareTrendStrategy:
        return RegimeAwareTrendStrategy(
            fast=int(params["fast"]),
            slow=int(params["slow"]),
            high_vol_weight=float(params["high_vol_weight"]),
        )

    wf, selections = walk_forward_grid_search(
        data,
        builder,
        engine,
        {
            "fast": [5, 10, 15],
            "slow": [20, 30, 40],
            "high_vol_weight": [0.0, 0.25],
        },
        train_size=train,
        test_size=test,
        step_size=test,
        score_key="sharpe",
    )
    cols = [
        "fold",
        "train_end",
        "test_end",
        "param_fast",
        "param_slow",
        "param_high_vol_weight",
        "train_score",
        "oos_sharpe",
        "oos_total_return",
    ]
    print("\n=== Walk-forward OOS ===")
    print(selections[cols].round(4).to_string(index=False))
    print("\nOOS aggregate:")
    print(pd.Series(wf.combined_stats).round(4).to_string())


if __name__ == "__main__":
    main()
