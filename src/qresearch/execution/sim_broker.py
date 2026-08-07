"""Simulated broker with cash, positions, and proportional costs."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from qresearch.backtest.costs import CostModel
from qresearch.execution.adapter import BrokerAdapter
from qresearch.execution.types import Fill, Order, OrderSide, OrderStatus


@dataclass
class SimBrokerAdapter(BrokerAdapter):
    """Immediate market-fill simulator.

    BUY spends cash; SELL credits cash. Fees = notional * cost_rate.
    Shorting is allowed only if `allow_short=True`.
    """

    initial_cash: float = 100_000.0
    cost_model: CostModel = field(default_factory=CostModel)
    allow_short: bool = False
    cash: float = field(init=False)
    positions: dict[str, float] = field(default_factory=dict, init=False)
    fill_log: list[Fill] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        self.cash = float(self.initial_cash)
        self.positions = {}
        self.fill_log = []

    def submit_order(self, order: Order, *, price: float, timestamp: pd.Timestamp) -> Fill:
        if price <= 0 or pd.isna(price):
            order.status = OrderStatus.REJECTED
            raise ValueError(f"invalid fill price for {order.symbol}: {price}")

        qty = float(order.quantity)
        notional = qty * float(price)
        fee = notional * self.cost_model.cost_rate()
        signed = qty if order.side == OrderSide.BUY else -qty
        new_pos = self.positions.get(order.symbol, 0.0) + signed

        if not self.allow_short and new_pos < -1e-12:
            order.status = OrderStatus.REJECTED
            raise ValueError(f"shorting disabled for {order.symbol}")

        if order.side == OrderSide.BUY:
            spend = notional + fee
            if spend > self.cash + 1e-9:
                order.status = OrderStatus.REJECTED
                raise ValueError(
                    f"insufficient cash: need {spend:.2f}, have {self.cash:.2f}"
                )
            self.cash -= spend
        else:
            self.cash += notional - fee

        self.positions[order.symbol] = new_pos
        if abs(self.positions[order.symbol]) < 1e-12:
            self.positions.pop(order.symbol, None)

        order.status = OrderStatus.FILLED
        fill = Fill(
            order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=qty,
            price=float(price),
            fee=fee,
            timestamp=pd.Timestamp(timestamp),
        )
        self.fill_log.append(fill)
        return fill

    def get_positions(self) -> dict[str, float]:
        return dict(self.positions)

    def get_cash(self) -> float:
        return float(self.cash)

    def get_equity(self, marks: dict[str, float]) -> float:
        equity = self.cash
        for sym, qty in self.positions.items():
            px = marks.get(sym)
            if px is None or pd.isna(px):
                raise KeyError(f"missing mark price for {sym}")
            equity += qty * float(px)
        return float(equity)

    def fills(self) -> list[Fill]:
        return list(self.fill_log)
