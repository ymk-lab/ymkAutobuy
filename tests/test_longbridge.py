from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from qresearch.brokers.longbridge.adapter import LongbridgeBrokerAdapter
from qresearch.brokers.longbridge.feed import LongbridgePollingFeed
from qresearch.brokers.longbridge.history import candlesticks_to_ohlcv
from qresearch.brokers.longbridge.symbols import normalize_symbol
from qresearch.execution.targets import TargetWeightExecutor
from qresearch.execution.types import Order, OrderSide, OrderType


def test_normalize_symbol():
    assert normalize_symbol("aapl.us") == "AAPL.US"
    assert normalize_symbol("700", default_market="HK") == "700.HK"
    with pytest.raises(ValueError):
        normalize_symbol("AAPL")


def test_dry_run_adapter_local_ledger():
    broker = LongbridgeBrokerAdapter(dry_run=True, initial_cash=10_000)
    ts = pd.Timestamp("2024-06-03")
    buy = Order(symbol="700.HK", side=OrderSide.BUY, quantity=10, order_type=OrderType.MARKET)
    fill = broker.submit_order(buy, price=100.0, timestamp=ts)
    assert fill.order_id.startswith("dry-")
    assert broker.get_positions()["700.HK"] == 10
    assert broker.get_cash() == pytest.approx(9000.0)
    assert broker.get_equity({"700.HK": 100.0}) == pytest.approx(10_000.0)


def test_live_submit_uses_trade_ctx_and_polls_fill():
    class FakeTrade:
        def __init__(self):
            self.submitted = None

        def submit_order(self, **kwargs):
            self.submitted = kwargs
            return SimpleNamespace(order_id="OID-1")

        def order_detail(self, order_id=None, **kwargs):
            from longbridge.openapi import OrderStatus

            return SimpleNamespace(
                status=OrderStatus.Filled,
                executed_quantity=8,
                executed_price=12.5,
            )

        def account_balance(self):
            return [
                SimpleNamespace(
                    currency="HKD",
                    total_cash=1000,
                    net_assets=1500,
                    cash_infos=[
                        SimpleNamespace(currency="HKD", available_cash=1000),
                    ],
                )
            ]

        def stock_positions(self):
            return SimpleNamespace(
                channels=[
                    SimpleNamespace(
                        positions=[
                            SimpleNamespace(symbol="700.HK", quantity=8),
                        ]
                    )
                ]
            )

    trade = FakeTrade()
    broker = LongbridgeBrokerAdapter(trade_ctx=trade, dry_run=False, currency="HKD")
    order = Order(symbol="700.HK", side=OrderSide.BUY, quantity=8.9)  # quantized to 8
    fill = broker.submit_order(order, price=12.0, timestamp=pd.Timestamp("2024-01-02"))
    assert trade.submitted["symbol"] == "700.HK"
    assert fill.order_id == "OID-1"
    assert fill.quantity == 8
    assert fill.price == 12.5
    assert broker.get_cash() == 1000
    assert broker.get_positions()["700.HK"] == 8
    assert broker.get_equity({"700.HK": 12.5}) == 1500


def test_candlesticks_to_ohlcv_and_polling_feed():
    candles = [
        SimpleNamespace(
            timestamp=pd.Timestamp("2024-01-02"),
            open=1,
            high=2,
            low=0.5,
            close=1.5,
            volume=100,
        ),
        SimpleNamespace(
            timestamp=pd.Timestamp("2024-01-03"),
            open=1.5,
            high=2.5,
            low=1.2,
            close=2.0,
            volume=120,
        ),
    ]
    df = candlesticks_to_ohlcv(candles)
    assert len(df) == 2
    assert df.iloc[-1]["close"] == 2.0

    class FakeQuote:
        def quote(self, symbols):
            return [
                SimpleNamespace(
                    symbol=symbols[0],
                    open=10,
                    high=11,
                    low=9,
                    last_done=10.5,
                    volume=1000,
                    timestamp=pd.Timestamp("2024-01-04"),
                )
            ]

    feed = LongbridgePollingFeed(
        symbols=["AAPL.US"],
        quote_ctx=FakeQuote(),
        interval_sec=0.0,
        max_bars=1,
    )
    batches = list(feed)
    assert len(batches) == 1
    assert "AAPL.US" in batches[0]
    assert batches[0]["AAPL.US"].close == 10.5


def test_target_executor_with_longbridge_dry_run():
    broker = LongbridgeBrokerAdapter(dry_run=True, initial_cash=100_000)
    ex = TargetWeightExecutor(broker, cash_buffer=0.0, min_trade_notional=1)
    fills = ex.rebalance(
        {"700.HK": 1.0},
        {"700.HK": 50.0},
        pd.Timestamp("2024-01-05"),
    )
    assert len(fills) == 1
    assert broker.get_positions()["700.HK"] == pytest.approx(2000.0)
