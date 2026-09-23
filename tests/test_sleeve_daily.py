from __future__ import annotations

from pathlib import Path

from qresearch.paper.sleeve_daily import annotate_marks, record_sleeve_day, realized_slip


def test_buy_above_mark_is_positive_cost():
    s = realized_slip(side="buy", fill_price=100.31, mark_price=100.0, quantity=10)
    assert round(s["realized_slip_bps"], 6) == 31.0
    assert round(s["realized_slip_usd"], 6) == 3.1


def test_sell_below_mark_is_positive_cost():
    s = realized_slip(side="sell", fill_price=99.5, mark_price=100.0, quantity=10)
    assert s["realized_slip_bps"] == 50.0
    assert s["realized_slip_usd"] == 5.0


def test_annotate_and_daily_pnl(tmp_path: Path):
    record_sleeve_day(
        tmp_path,
        asof="2026-09-21",
        job="once",
        env="SIMULATE",
        sleeve_notional=50_000,
        cash=25_000,
        equity=50_000,
        positions={"QQQ.US": 25},
        marks={"QQQ.US": 500.0},
        fills=[],
    )
    day = record_sleeve_day(
        tmp_path,
        asof="2026-09-22",
        job="once",
        env="SIMULATE",
        sleeve_notional=50_000,
        cash=24_000,
        equity=50_200,
        positions={"QQQ.US": 26},
        marks={"QQQ.US": 500.0},
        fills=[{"symbol": "QQQ.US", "side": "buy", "quantity": 1, "price": 501.5}],
    )
    assert day["day_pnl"] == 200.0
    assert day["n_fills"] == 1
    assert day["realized_slip_bps"] == 30.0
    assert day["realized_slip_usd"] == 1.5


def test_once_overwrites_same_asof_signal(tmp_path: Path):
    record_sleeve_day(
        tmp_path,
        asof="2026-09-22",
        job="signal",
        env="SIMULATE",
        sleeve_notional=50_000,
        cash=50_000,
        equity=50_000,
        positions={},
        marks={},
        fills=[],
    )
    record_sleeve_day(
        tmp_path,
        asof="2026-09-22",
        job="once",
        env="SIMULATE",
        sleeve_notional=50_000,
        cash=49_000,
        equity=50_100,
        positions={"SPY.US": 10},
        marks={"SPY.US": 500.0},
        fills=[],
    )
    lines = (tmp_path / "sleeve_daily.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    assert '"job": "once"' in lines[0]
