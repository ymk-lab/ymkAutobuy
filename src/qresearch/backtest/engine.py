"""Vectorized single-asset research backtester with next-bar execution."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from qresearch.backtest.costs import CostModel
from qresearch.data.loader import validate_ohlcv
from qresearch.metrics.performance import summarize_performance
from qresearch.strategy.base import Strategy


@dataclass
class BacktestResult:
    equity: pd.Series
    returns: pd.Series
    positions: pd.Series
    turnover: pd.Series
    costs: pd.Series
    signals: pd.Series
    regimes: pd.Series | None
    stats: dict[str, float]
    trades: pd.DataFrame

    def summary(self) -> pd.Series:
        return pd.Series(self.stats)


class BacktestEngine:
    """Research backtest engine.

    Design choices (intentional for research honesty):
    - Signal at bar t is executed at bar t+1 open (next-bar execution)
    - Positions are target weights in [-1, 1] by default
    - Costs applied on absolute weight changes (turnover)
    - No lookahead: strategy only sees data available at decision time
    """

    def __init__(
        self,
        *,
        initial_capital: float = 100_000.0,
        cost_model: CostModel | None = None,
        allow_short: bool = True,
        position_clip: float = 1.0,
    ) -> None:
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        self.initial_capital = initial_capital
        self.cost_model = cost_model or CostModel()
        self.allow_short = allow_short
        self.position_clip = abs(position_clip)

    def run(self, data: pd.DataFrame, strategy: Strategy) -> BacktestResult:
        ohlcv = validate_ohlcv(data)
        raw_signal = strategy.generate_signals(ohlcv)
        if not isinstance(raw_signal, pd.Series):
            raise TypeError("strategy.generate_signals must return a Series")
        signal = raw_signal.reindex(ohlcv.index).astype(float)

        regimes = None
        if hasattr(strategy, "generate_regimes"):
            regimes = strategy.generate_regimes(ohlcv)
            if regimes is not None:
                regimes = regimes.reindex(ohlcv.index)

        # Next-bar execution: decide at t close, trade at t+1 open.
        target = signal.shift(1).fillna(0.0)
        target = target.clip(-self.position_clip, self.position_clip)
        if not self.allow_short:
            target = target.clip(lower=0.0)

        open_px = ohlcv["open"].astype(float)
        close_px = ohlcv["close"].astype(float)
        # Intrabar return while holding position decided previous bar.
        asset_ret = close_px / open_px - 1.0
        # Overnight gap from previous close to today's open is also earned
        # by the position carried into today (target already shifted).
        gap_ret = open_px / close_px.shift(1) - 1.0
        gap_ret = gap_ret.fillna(0.0)
        gross_ret = target * (gap_ret + asset_ret)

        turnover = target.diff().abs().fillna(target.abs())
        cost_ret = turnover * self.cost_model.cost_rate()
        net_ret = gross_ret - cost_ret

        equity = (1.0 + net_ret).cumprod() * self.initial_capital
        trades = self._build_trades(target, open_px, cost_ret)

        stats = summarize_performance(
            returns=net_ret,
            equity=equity,
            turnover=turnover,
            positions=target,
        )

        return BacktestResult(
            equity=equity.rename("equity"),
            returns=net_ret.rename("returns"),
            positions=target.rename("position"),
            turnover=turnover.rename("turnover"),
            costs=cost_ret.rename("costs"),
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
            return pd.DataFrame(
                columns=["datetime", "delta_weight", "open", "cost_return"]
            )

        out = pd.DataFrame(
            {
                "datetime": positions.index[mask],
                "delta_weight": delta[mask].to_numpy(),
                "open": open_px[mask].to_numpy(),
                "cost_return": cost_ret[mask].to_numpy(),
            }
        )
        return out.reset_index(drop=True)
