"""qresearch: research-first quantitative backtesting."""

from qresearch.backtest.engine import BacktestEngine, BacktestResult
from qresearch.backtest.costs import CostModel
from qresearch.metrics.performance import summarize_performance
from qresearch.strategy.base import Strategy

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "CostModel",
    "Strategy",
    "summarize_performance",
]

__version__ = "0.1.0"
