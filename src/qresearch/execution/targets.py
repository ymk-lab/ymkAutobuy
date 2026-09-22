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
    cash_buffer: float = 0.01
    rebalance_band: float = 0.0

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
        gross_eq = eq
        eq *= max(0.0, 1.0 - self.cash_buffer)

        positions = {str(k).upper(): float(v) for k, v in self.broker.get_positions().items()}
        symbols = sorted(set(marks) | set(positions) | {str(k).upper() for k in target_weights})
        flatten = all(float(w) <= 1e-12 for w in target_weights.values()) and any(
            abs(q) > self.min_qty for q in positions.values()
        )

        sells: list[Order] = []
        buys: list[Order] = []
        for sym in symbols:
            px = marks.get(sym)
            if px is None or px <= 0 or pd.isna(px):
                continue
            target_w = float(target_weights.get(sym, 0.0))
            target_qty = (target_w * eq) / px
            current_qty = positions.get(sym, 0.0)
            current_w = (current_qty * px / gross_eq) if gross_eq > 0 else 0.0
            is_entry = abs(current_qty) < self.min_qty and target_w > 1e-12
            is_exit = target_w <= 1e-12 and abs(current_qty) >= self.min_qty
            if (
                self.rebalance_band > 0
                and not flatten
                and not is_entry
                and not is_exit
                and abs(target_w - current_w) < self.rebalance_band
            ):
                continue
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
        errors: list[str] = []
        for order in sells + buys:
            try:
                fills.append(
                    self.broker.submit_order(
                        order,
                        price=marks[order.symbol],
                        timestamp=pd.Timestamp(timestamp),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                side = order.side.value if hasattr(order.side, "value") else str(order.side)
                errors.append(f"{side} {order.quantity:g} {order.symbol}: {exc}")
        if errors:
            raise RuntimeError("rebalance partial failure: " + " | ".join(errors))
        return fills
