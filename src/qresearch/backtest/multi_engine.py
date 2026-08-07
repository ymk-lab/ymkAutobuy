"""Multi-asset research backtester with risk-budgeted weights."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from qresearch.backtest.costs import CostModel
from qresearch.data.panel import align_panel, panel_close
from qresearch.metrics.performance import summarize_performance
from qresearch.portfolio.risk import RiskBudgetConfig, allocate_risk_budget
from qresearch.strategy.multi import MultiAssetStrategy


@dataclass
class MultiBacktestResult:
    equity: pd.Series
    returns: pd.Series
    weights: pd.DataFrame
    signals: pd.DataFrame
    turnover: pd.Series
    costs: pd.Series
    stats: dict[str, float]

    def summary(self) -> pd.Series:
        return pd.Series(self.stats)


class MultiBacktestEngine:
    """Multi-asset engine.

    - Strategy emits raw signals
    - Risk budget converts signals → target weights
    - Next-bar execution on open
    - Costs charged on sum of absolute weight changes
    """

    def __init__(
        self,
        *,
        initial_capital: float = 100_000.0,
        cost_model: CostModel | None = None,
        risk_config: RiskBudgetConfig | None = None,
    ) -> None:
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        self.initial_capital = initial_capital
        self.cost_model = cost_model or CostModel()
        self.risk_config = risk_config or RiskBudgetConfig()

    def run(
        self,
        panel: dict[str, pd.DataFrame],
        strategy: MultiAssetStrategy,
    ) -> MultiBacktestResult:
        aligned = align_panel(panel)
        closes = panel_close(aligned)

        signals = strategy.generate_signals(aligned)
        if not isinstance(signals, pd.DataFrame):
            raise TypeError("multi strategy must return a DataFrame")
        signals = signals.reindex(index=closes.index, columns=closes.columns).fillna(0.0)

        raw_weights = allocate_risk_budget(signals, closes, self.risk_config)
        # Next-bar execution
        weights = raw_weights.shift(1).fillna(0.0)

        # Close-to-close asset returns (aligned with PaperBroker).
        asset_ret = closes.pct_change().fillna(0.0)
        gross = (weights * asset_ret).sum(axis=1)

        turnover = weights.diff().abs().sum(axis=1).fillna(weights.abs().sum(axis=1))
        cost_ret = turnover * self.cost_model.cost_rate()
        net = gross - cost_ret

        equity = (1.0 + net).cumprod() * self.initial_capital
        # Representative position magnitude for metrics
        abs_pos = weights.abs().sum(axis=1)
        stats = summarize_performance(
            returns=net,
            equity=equity,
            turnover=turnover,
            positions=abs_pos,
        )
        stats["avg_gross_exposure"] = float(abs_pos.mean())
        stats["avg_net_exposure"] = float(weights.sum(axis=1).mean())
        stats["n_assets"] = float(closes.shape[1])

        return MultiBacktestResult(
            equity=equity.rename("equity"),
            returns=net.rename("returns"),
            weights=weights,
            signals=signals,
            turnover=turnover.rename("turnover"),
            costs=cost_ret.rename("costs"),
            stats=stats,
        )
