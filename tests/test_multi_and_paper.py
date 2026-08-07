from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from qresearch.backtest.costs import CostModel
from qresearch.backtest.multi_engine import MultiBacktestEngine
from qresearch.data.panel import (
    generate_synthetic_panel,
    load_panel_csv_dir,
    panel_close,
    save_panel_csv_dir,
)
from qresearch.paper.broker import replay_paper_from_weights
from qresearch.portfolio.risk import RiskBudgetConfig, allocate_risk_budget
from qresearch.strategy.multi import CrossSectionalMomentumStrategy


def test_allocate_inverse_vol_respects_gross_and_long_only():
    idx = pd.bdate_range("2024-01-01", periods=80)
    closes = pd.DataFrame(
        {
            "A": np.linspace(100, 120, 80),
            "B": np.linspace(100, 90, 80),
            "C": np.linspace(100, 110, 80),
        },
        index=idx,
    )
    signals = pd.DataFrame(1.0, index=idx, columns=list("ABC"))
    weights = allocate_risk_budget(
        signals,
        closes,
        RiskBudgetConfig(
            vol_lookback=10,
            invert_vol=True,
            target_gross=1.0,
            max_weight=0.6,
            allow_short=False,
        ),
    )
    tail = weights.iloc[20:]
    assert (tail >= -1e-12).all().all()
    gross = tail.abs().sum(axis=1)
    assert (gross <= 1.0 + 1e-8).all()
    assert (tail.max(axis=1) <= 0.6 + 1e-8).all()


def test_multi_engine_runs_and_has_stats():
    panel = generate_synthetic_panel(("AAA", "BBB", "CCC"), n=300, seed=3)
    result = MultiBacktestEngine(
        risk_config=RiskBudgetConfig(target_vol=None, vol_lookback=15)
    ).run(panel, CrossSectionalMomentumStrategy(lookback=10, top_fraction=0.34))
    assert len(result.equity) == 300
    assert "sharpe" in result.stats
    assert result.stats["n_assets"] == 3


def test_panel_csv_roundtrip(tmp_path: Path):
    panel = generate_synthetic_panel(("AAA", "BBB"), n=50, seed=4)
    save_panel_csv_dir(panel, tmp_path / "panel")
    loaded = load_panel_csv_dir(tmp_path / "panel")
    assert set(loaded) == {"AAA", "BBB"}
    assert len(next(iter(loaded.values()))) == 50


def test_paper_replay_matches_multi_backtest():
    panel = generate_synthetic_panel(("AAA", "BBB", "CCC"), n=260, seed=5)
    cost = CostModel(fee_bps=2.0, slippage_bps=2.0)
    engine = MultiBacktestEngine(
        initial_capital=100_000.0,
        cost_model=cost,
        risk_config=RiskBudgetConfig(
            vol_lookback=15,
            invert_vol=True,
            target_gross=1.0,
            target_vol=None,
            max_weight=0.5,
        ),
    )
    result = engine.run(panel, CrossSectionalMomentumStrategy(lookback=15))
    paper = replay_paper_from_weights(
        result.weights,
        panel_close(panel),
        initial_capital=100_000.0,
        cost_model=cost,
    )
    aligned = pd.concat([result.equity, paper], axis=1).dropna()
    rel = (aligned.iloc[:, 1] / aligned.iloc[:, 0] - 1.0).abs()
    assert float(rel.max()) < 1e-8
