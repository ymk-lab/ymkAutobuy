from __future__ import annotations

import pandas as pd
import pytest

from qresearch.backtest.costs import CostModel
from qresearch.data.panel import generate_synthetic_panel
from qresearch.execution.sim_broker import SimBrokerAdapter
from qresearch.execution.targets import TargetWeightExecutor
from qresearch.execution.types import Order, OrderSide
from qresearch.live.feed import HistoricalReplayFeed
from qresearch.live.loop import LiveConfig, LiveTradingLoop
from qresearch.portfolio.risk import RiskBudgetConfig
from qresearch.strategy.multi import CrossSectionalMomentumStrategy


def test_sim_broker_buy_sell_and_fees():
    broker = SimBrokerAdapter(
        initial_cash=10_000,
        cost_model=CostModel(fee_bps=10, slippage_bps=0),
    )
    ts = pd.Timestamp("2024-01-02")
    buy = Order(symbol="AAA", side=OrderSide.BUY, quantity=10)
    fill = broker.submit_order(buy, price=100.0, timestamp=ts)
    assert fill.fee == pytest.approx(1.0)  # 1000 * 10bps
    assert broker.get_cash() == pytest.approx(10_000 - 1000 - 1)
    assert broker.get_positions()["AAA"] == pytest.approx(10)

    sell = Order(symbol="AAA", side=OrderSide.SELL, quantity=10)
    broker.submit_order(sell, price=100.0, timestamp=ts)
    assert broker.get_positions() == {}
    assert broker.get_cash() == pytest.approx(10_000 - 2.0)


def test_target_weight_executor_reaches_rough_weights():
    broker = SimBrokerAdapter(initial_cash=100_000, cost_model=CostModel(0, 0))
    ex = TargetWeightExecutor(broker, cash_buffer=0.0, min_trade_notional=1.0)
    prices = {"AAA": 50.0, "BBB": 25.0}
    ts = pd.Timestamp("2024-01-03")
    fills = ex.rebalance({"AAA": 0.5, "BBB": 0.5}, prices, ts)
    assert len(fills) == 2
    eq = broker.get_equity(prices)
    w_aaa = broker.get_positions()["AAA"] * 50 / eq
    w_bbb = broker.get_positions()["BBB"] * 25 / eq
    assert w_aaa == pytest.approx(0.5, abs=1e-6)
    assert w_bbb == pytest.approx(0.5, abs=1e-6)


def test_historical_feed_emits_synced_batches():
    panel = generate_synthetic_panel(("AAA", "BBB"), n=5, seed=1)
    batches = list(HistoricalReplayFeed(panel))
    assert len(batches) == 5
    assert set(batches[0]) == {"AAA", "BBB"}
    assert batches[0]["AAA"].timestamp == batches[0]["BBB"].timestamp


def test_live_loop_runs_and_trades():
    panel = generate_synthetic_panel(("AAA", "BBB", "CCC"), n=120, seed=2)
    broker = SimBrokerAdapter(
        initial_cash=100_000,
        cost_model=CostModel(fee_bps=1, slippage_bps=1),
    )
    result = LiveTradingLoop(
        feed=HistoricalReplayFeed(panel),
        strategy=CrossSectionalMomentumStrategy(lookback=10, top_fraction=0.34),
        broker=broker,
        risk_config=RiskBudgetConfig(vol_lookback=10, target_vol=None, max_weight=0.6),
        config=LiveConfig(min_history=30, max_drawdown=0.9),
    ).run()
    assert result.bars_processed == 120
    assert len(result.equity) == 120
    assert len(result.fills) > 0
    assert result.equity.iloc[-1] > 0


def test_live_loop_kill_switch_flattens():
    panel = generate_synthetic_panel(("AAA", "BBB"), n=150, seed=3)
    broker = SimBrokerAdapter(initial_cash=100_000, cost_model=CostModel(1, 1))
    result = LiveTradingLoop(
        feed=HistoricalReplayFeed(panel),
        strategy=CrossSectionalMomentumStrategy(lookback=5, top_fraction=0.5),
        broker=broker,
        risk_config=RiskBudgetConfig(vol_lookback=8, target_vol=None),
        config=LiveConfig(min_history=20, max_drawdown=0.0001, flatten_on_stop=True),
    ).run()
    # Extremely tight DD should stop quickly after trading begins.
    assert result.stopped is True
    assert result.stop_reason is not None
    # After flatten, positions should be empty (or tiny residual).
    assert sum(abs(v) for v in broker.get_positions().values()) == pytest.approx(0.0, abs=1e-6)
