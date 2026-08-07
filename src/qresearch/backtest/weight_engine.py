"""Single-asset backtest with next-bar weights and dollar fee models."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from qresearch.backtest.engine import BacktestResult
from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.data.loader import validate_ohlcv
from qresearch.metrics.performance import summarize_performance
from qresearch.strategy.base import Strategy


@dataclass
class WeightBacktestEngine:
    """Like BacktestEngine, but costs come from FutuUsEquityFees on traded notional."""

    initial_capital: float = 50_000.0
    fees: FutuUsEquityFees | None = None
    allow_short: bool = False
    position_clip: float = 1.0
    # Ignore tiny retunes so Futu per-order mins do not dominate soft-vol drift.
    trade_threshold: float = 0.02
    # "threshold" = classic band; "event" = trade on strategy event_mask or band breach
    rebalance_mode: str = "threshold"

    def __post_init__(self) -> None:
        if self.fees is None:
            self.fees = FutuUsEquityFees()
        mode = self.rebalance_mode.lower()
        if mode not in {"threshold", "event"}:
            raise ValueError("rebalance_mode must be 'threshold' or 'event'")
        self.rebalance_mode = mode

    def run(self, data: pd.DataFrame, strategy: Strategy) -> BacktestResult:
        assert self.fees is not None
        ohlcv = validate_ohlcv(data)
        raw_signal = strategy.generate_signals(ohlcv)
        signal = raw_signal.reindex(ohlcv.index).astype(float).fillna(0.0)
        regimes = None
        if hasattr(strategy, "generate_regimes"):
            regimes = strategy.generate_regimes(ohlcv)
            if regimes is not None:
                regimes = regimes.reindex(ohlcv.index)

        event = None
        if hasattr(strategy, "last_event_mask") and strategy.last_event_mask is not None:
            event = strategy.last_event_mask.reindex(ohlcv.index).fillna(False).to_numpy()

        desired = signal.shift(1).fillna(0.0).clip(-self.position_clip, self.position_clip)
        if not self.allow_short:
            desired = desired.clip(lower=0.0)
        # shift event mask with signal (decide t, trade t+1)
        if event is not None:
            event_exec = pd.Series(event, index=ohlcv.index).shift(1).fillna(True).to_numpy(dtype=bool)
        else:
            event_exec = np.ones(len(ohlcv), dtype=bool)

        executed = np.zeros(len(desired), dtype=float)
        prev = 0.0
        thr = float(self.trade_threshold)
        for i, w in enumerate(desired.to_numpy(dtype=float)):
            force = bool(event_exec[i]) if self.rebalance_mode == "event" else False
            if self.rebalance_mode == "event":
                if force and abs(w - prev) > 1e-12:
                    prev = w
                elif prev == 0.0 and w != 0.0 and force:
                    prev = w
                elif w == 0.0 and prev != 0.0 and force:
                    prev = 0.0
                elif abs(w - prev) >= thr:
                    prev = w
            else:
                if prev == 0.0 and w != 0.0:
                    prev = w
                elif w == 0.0 and prev != 0.0:
                    prev = 0.0
                elif abs(w - prev) >= thr:
                    prev = w
            executed[i] = prev
        target = pd.Series(executed, index=ohlcv.index, name="position")
        open_px = ohlcv["open"].astype(float)
        close_px = ohlcv["close"].astype(float)
        asset_ret = close_px / open_px - 1.0
        gap_ret = (open_px / close_px.shift(1) - 1.0).fillna(0.0)

        turnover = target.diff().abs().fillna(target.abs())
        n = len(ohlcv)
        equity = np.empty(n, dtype=float)
        net_ret = np.empty(n, dtype=float)
        costs = np.empty(n, dtype=float)
        eq = float(self.initial_capital)

        for i in range(n):
            w = float(target.iloc[i])
            t_turn = float(turnover.iloc[i])
            cost_frac = self.fees.cost_return_on_equity(t_turn, eq, float(open_px.iloc[i]))
            gross = w * (float(gap_ret.iloc[i]) + float(asset_ret.iloc[i]))
            r = gross - cost_frac
            eq = eq * (1.0 + r)
            net_ret[i] = r
            costs[i] = cost_frac
            equity[i] = eq

        equity_s = pd.Series(equity, index=ohlcv.index, name="equity")
        returns_s = pd.Series(net_ret, index=ohlcv.index, name="returns")
        costs_s = pd.Series(costs, index=ohlcv.index, name="costs")
        stats = summarize_performance(
            returns=returns_s,
            equity=equity_s,
            turnover=turnover,
            positions=target,
        )
        trades = self._build_trades(target, open_px, costs_s)
        return BacktestResult(
            equity=equity_s,
            returns=returns_s,
            positions=target.rename("position"),
            turnover=turnover.rename("turnover"),
            costs=costs_s,
            signals=signal.rename("signal"),
            regimes=regimes.rename("regime") if regimes is not None else None,
            stats=stats,
            trades=trades,
        )

    @staticmethod
    def _build_trades(
        positions: pd.Series,
        open_px: pd.Series,
        cost_ret: pd.Series,
    ) -> pd.DataFrame:
        delta = positions.diff().fillna(positions)
        mask = delta.abs() > 1e-12
        if not mask.any():
            return pd.DataFrame(columns=["datetime", "delta_weight", "open", "cost_return"])
        return pd.DataFrame(
            {
                "datetime": positions.index[mask],
                "delta_weight": delta[mask].to_numpy(),
                "open": open_px[mask].to_numpy(),
                "cost_return": cost_ret[mask].to_numpy(),
            }
        ).reset_index(drop=True)
