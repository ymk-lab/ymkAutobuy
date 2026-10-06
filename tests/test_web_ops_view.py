"""Ops panel is a read-only view. It must not change strategy or order logic."""

from qresearch.ops.control import freeze
from qresearch.ops.plan import write_locked_plan
from qresearch.paper.sleeve_daily import record_sleeve_day
from qresearch.web.paper_app import _money_ledger, _ops_view


def test_ops_view_reads_freeze_plan_notional_and_blotter(tmp_path):
    freeze(tmp_path, "OpenD down")
    write_locked_plan(
        tmp_path,
        {"asof": "2026-10-02", "target": {"QQQ.US": 0.5, "SPY.US": 0.5}},
    )
    record_sleeve_day(
        tmp_path,
        asof="2026-10-02",
        job="once",
        env="SIMULATE",
        sleeve_notional=40_000,
        cash=12_000,
        equity=40_000,
        positions={"QQQ.US": 20},
        marks={"QQQ.US": 500},
        fills=[
            {"symbol": "QQQ.US", "side": "buy", "price": 501, "quantity": 2, "fee": 1.0},
        ],
    )

    view = _ops_view(tmp_path, 40_000)

    assert view["frozen"] is True
    assert view["freeze_reason"] == "OpenD down"
    assert view["consumed_by_daily"] is False
    assert view["notional_cap"] == 50_000
    assert view["sleeve_notional"] == 40_000
    assert view["rebalance_band_rule"] == 0.02
    assert view["rebalance_band_active"] == 0.0
    assert view["locked_plan"]["asof"] == "2026-10-02"
    assert view["locked_plan"]["locked"] is True
    assert view["sleeve_days"][-1]["asof"] == "2026-10-02"
    assert view["sleeve_days"][-1]["n_fills"] == 1

    fallback = _ops_view(tmp_path, None)
    assert fallback["sleeve_notional"] == 40_000


def test_money_ledger_traces_cash_and_realized_pnl():
    ledger = _money_ledger(
        [
            {"symbol": "QQQ.US", "side": "buy", "quantity": 10, "price": 100, "fee": 1, "asof": "2026-10-01"},
            {"symbol": "QQQ.US", "side": "sell", "quantity": 4, "price": 110, "fee": 1, "asof": "2026-10-02"},
        ]
    )
    assert ledger["n"] == 2
    assert ledger["buy_notional"] == 1000
    assert ledger["sell_notional"] == 440
    assert ledger["fees"] == 2
    buy, sell = ledger["rows"]
    assert buy["cash"] == -1001
    assert buy["position_after"] == 10
    assert abs(buy["avg_cost_after"] - 100.1) < 1e-9
    assert sell["realized_pnl"] is not None
    assert abs(sell["realized_pnl"] - (440 - 1 - 100.1 * 4)) < 1e-9
    assert sell["position_after"] == 6
