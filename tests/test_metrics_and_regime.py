from __future__ import annotations

import pandas as pd

from qresearch.backtest.engine import BacktestEngine
from qresearch.data.loader import validate_ohlcv
from qresearch.data.synthetic import generate_synthetic_ohlcv
from qresearch.metrics.performance import summarize_performance
from qresearch.regime.detector import VolatilityRegimeDetector
from qresearch.strategy.examples import RegimeAwareTrendStrategy


def test_validate_ohlcv_rejects_duplicates():
    data = generate_synthetic_ohlcv(n=30, seed=1)
    bad = pd.concat([data, data.iloc[[-1]]])
    try:
        validate_ohlcv(bad)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "duplicate" in str(exc).lower()


def test_regime_detector_labels():
    data = generate_synthetic_ohlcv(n=200, seed=5, regime_breaks=(80,))
    labels = VolatilityRegimeDetector(lookback=20).detect(data)
    assert set(labels.unique()) <= {"unknown", "low_vol", "high_vol"}
    assert (labels.iloc[:19] == "unknown").all()


def test_regime_strategy_flattens_in_high_vol():
    data = generate_synthetic_ohlcv(n=400, seed=6, regime_breaks=(100, 250))
    strategy = RegimeAwareTrendStrategy(fast=5, slow=20, high_vol_weight=0.0)
    signals = strategy.generate_signals(data)
    regimes = strategy.generate_regimes(data)
    high = regimes == "high_vol"
    if high.any():
        assert (signals[high] == 0.0).all()


def test_summarize_performance_keys():
    idx = pd.bdate_range("2024-01-01", periods=50)
    rets = pd.Series(0.001, index=idx)
    equity = (1 + rets).cumprod() * 1000
    stats = summarize_performance(
        returns=rets,
        equity=equity,
        turnover=pd.Series(0.1, index=idx),
        positions=pd.Series(1.0, index=idx),
    )
    assert stats["total_return"] > 0
    assert "sharpe" in stats
    assert "max_drawdown" in stats


def test_engine_attaches_regimes():
    data = generate_synthetic_ohlcv(n=180, seed=8)
    result = BacktestEngine().run(data, RegimeAwareTrendStrategy())
    assert result.regimes is not None
    assert len(result.regimes) == len(data)
