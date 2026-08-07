"""qresearch: research-first quantitative backtesting."""

from qresearch.backtest.costs import CostModel
from qresearch.backtest.engine import BacktestEngine, BacktestResult
from qresearch.backtest.multi_engine import MultiBacktestEngine, MultiBacktestResult
from qresearch.metrics.performance import summarize_performance
from qresearch.portfolio.risk import RiskBudgetConfig
from qresearch.strategy.base import Strategy

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "MultiBacktestEngine",
    "MultiBacktestResult",
    "CostModel",
    "RiskBudgetConfig",
    "Strategy",
    "summarize_performance",
]

__version__ = "0.2.0"
