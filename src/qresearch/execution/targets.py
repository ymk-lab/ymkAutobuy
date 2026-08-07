"""Convert target portfolio weights into executable orders."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from qresearch.execution.adapter import BrokerAdapter
from qresearch.execution.types import Fill, Order, OrderSide, OrderType


@dataclass
class TargetWeightExecutor:
    """Translate desired weights into market orders against a broker."""

    broker: BrokerAdapter
    min_trade_notional: float = 1.0
    min_qty: float = 1e-8
    # Leave a small cash cushion so fees / rounding don't reject buys.
    cash_buffer: float = 0.01

    def rebalance(
        self,
        target_weights: dict[str, float] | pd.Series,
        prices: dict[str, float],
        timestamp: pd.Timestamp,
        *,
        equity: float | None = None,
    ) -> list[Fill]:
        if isinstance(target_weights, pd.Series):
            target_weights = target_weights.to_dict()

        marks = {str(k).upper(): float(v) for k, v in prices.items()}
        eq = float(equity) if equity is not None else self.broker.get_equity(marks)
        if eq <= 0:
            raise ValueError("equity must be positive to rebalance")
        eq *= max(0.0, 1.0 - self.cash_buffer)

        positions = {str(k).upper(): float(v) for k, v in self.broker.get_positions().items()}
        symbols = sorted(set(marks) | set(positions) | {str(k).upper() for k in target_weights})

        # Build orders first (sells before buys helps cash availability).
        sells: list[Order] = []
        buys: list[Order] = []
        for sym in symbols:
            px = marks.get(sym)
            if px is None or px <= 0 or pd.isna(px):
                continue
            target_w = float(target_weights.get(sym, 0.0))
            target_qty = (target_w * eq) / px
            current_qty = positions.get(sym, 0.0)
            delta = target_qty - current_qty
            if abs(delta) * px < self.min_trade_notional or abs(delta) < self.min_qty:
                continue
            qty = abs(delta)
            quantize = getattr(self.broker, "quantize_quantity", None)
            if callable(quantize):
                qty = float(quantize(qty))
                if qty <= 0 or qty * px < self.min_trade_notional:
                    continue
            order = Order(
                symbol=sym,
                side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
                quantity=qty,
                order_type=OrderType.MARKET,
                created_at=pd.Timestamp(timestamp),
            )
            (buys if delta > 0 else sells).append(order)

        fills: list[Fill] = []
        for order in sells + buys:
            fills.append(
                self.broker.submit_order(
                    order,
                    price=marks[order.symbol],
                    timestamp=pd.Timestamp(timestamp),
                )
            )
        return fills
