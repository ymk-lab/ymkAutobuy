from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from qresearch.backtest.costs import CostModel
from qresearch.execution.sim_broker import SimBrokerAdapter
from qresearch.execution.targets import TargetWeightExecutor
from qresearch.ops.control import OpsState, freeze, load_ops, refuse_once_reason, unfreeze
from qresearch.ops.notional import sleeve_notional
from qresearch.ops.plan import load_locked_plan, slip_bps, write_locked_plan


def test_sleeve_notional_min_cap_equity():
    assert sleeve_notional(cap=20_000, equity=50_000) == 20_000
    assert sleeve_notional(cap=50_000, equity=30_000) == 30_000
    assert sleeve_notional(cap=50_000, equity=50_000, buying_power=80_000) == 50_000


def test_sleeve_notional_buying_power_opt_in():
    assert sleeve_notional(
        cap=50_000, equity=30_000, buying_power=80_000, buying_power_cap=True
    ) == 50_000
    assert sleeve_notional(
        cap=100_000, equity=30_000, buying_power=80_000, buying_power_cap=True
    ) == 80_000


def test_rebalance_band_skips_one_share_trim():
    broker = SimBrokerAdapter(initial_cash=1.0, cost_model=CostModel(0, 0))
    broker.cash = 0.0
    broker.positions = {"QQQ.US": 51.0}
    prices = {"QQQ.US": 500.0}
    ex = TargetWeightExecutor(
        broker, cash_buffer=0.0, min_trade_notional=1.0, rebalance_band=0.02
    )
    fills = ex.rebalance(
        {"QQQ.US": 0.50, "SPY.US": 0.0},
        prices,
        pd.Timestamp("2026-01-02"),
        equity=50_000,
    )
    assert fills == []


def test_rebalance_band_still_exits_to_cash():
    broker = SimBrokerAdapter(initial_cash=1.0, cost_model=CostModel(0, 0))
    broker.cash = 0.0
    broker.positions = {"QQQ.US": 50.0}
    prices = {"QQQ.US": 500.0}
    ex = TargetWeightExecutor(
        broker, cash_buffer=0.0, min_trade_notional=1.0, rebalance_band=0.02
    )
    fills = ex.rebalance({"QQQ.US": 0.0}, prices, pd.Timestamp("2026-01-02"), equity=25_000)
    assert len(fills) == 1
    assert fills[0].side.value == "sell"


def test_locked_plan_roundtrip(tmp_path: Path):
    write_locked_plan(tmp_path, {"asof": "2026-09-21", "target": {"QQQ.US": 0.5}, "sleeve_equity_usd": 50_000})
    plan = load_locked_plan(tmp_path)
    assert plan is not None
    assert plan["locked"] is True
    assert plan["asof"] == "2026-09-21"
    assert (tmp_path / "latest_signal.json").is_file()


def test_freeze_blocks_once(tmp_path: Path):
    freeze(tmp_path, "OpenD down")
    state = load_ops(tmp_path)
    reason = refuse_once_reason(
        state, opend_ok=True, plan_asof="2026-09-21", expected_asof="2026-09-21"
    )
    assert reason and reason.startswith("frozen")
    unfreeze(tmp_path)
    state = load_ops(tmp_path)
    assert refuse_once_reason(
        state, opend_ok=True, plan_asof="2026-09-21", expected_asof="2026-09-21"
    ) == "submit gate closed"


def test_real_refused_without_allow_live(monkeypatch):
    monkeypatch.delenv("QRESEARCH_FUTU_ALLOW_LIVE", raising=False)
    state = OpsState(submit_enabled=True, trading_env="REAL")
    reason = refuse_once_reason(
        state, opend_ok=True, plan_asof="2026-09-21", expected_asof="2026-09-21"
    )
    assert reason and "ALLOW_LIVE" in reason


def test_asof_mismatch_refuses_once():
    state = OpsState(submit_enabled=True, trading_env="SIMULATE")
    reason = refuse_once_reason(
        state, opend_ok=True, plan_asof="2026-09-18", expected_asof="2026-09-21"
    )
    assert reason and "asof" in reason.lower()


def test_slip_bps():
    assert slip_bps(100.0, 100.31) == pytest.approx(31.0)
    assert slip_bps(100.0, 100.51) > 50
