"""Longbridge BrokerAdapter implementation."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from typing import Any

import pandas as pd

from qresearch.brokers.longbridge.symbols import normalize_symbol
from qresearch.execution.adapter import BrokerAdapter
from qresearch.execution.types import Fill, Order, OrderSide, OrderStatus, OrderType


@dataclass
class LongbridgeBrokerAdapter(BrokerAdapter):
    """Route research orders to Longbridge OpenAPI.

    Safety:
    - `dry_run=True` (default) never calls `submit_order` on the venue.
    - When `trade_ctx` is provided, position/cash reads still hit the API.
    - Without `trade_ctx`, dry-run keeps a local cash/position ledger.

    Symbols must be `TICKER.MARKET` (e.g. `AAPL.US`, `700.HK`).
    """

    trade_ctx: Any = None
    quote_ctx: Any = None
    currency: str = "HKD"
    dry_run: bool = True
    default_market: str | None = None
    quantity_decimals: int = 0
    poll_fills: int = 5
    poll_interval_sec: float = 0.35
    remark_prefix: str = "qresearch"
    initial_cash: float = 100_000.0
    fill_log: list[Fill] = field(default_factory=list)
    _local_cash: float = field(init=False, repr=False)
    _local_positions: dict[str, float] = field(init=False, repr=False, default_factory=dict)

    def __post_init__(self) -> None:
        if self.trade_ctx is None and not self.dry_run:
            raise ValueError("trade_ctx is required when dry_run=False")
        self._local_cash = float(self.initial_cash)
        self._local_positions = {}

    @classmethod
    def from_env(
        cls,
        *,
        dry_run: bool = True,
        currency: str = "HKD",
        default_market: str | None = None,
        initial_cash: float = 100_000.0,
    ) -> "LongbridgeBrokerAdapter":
        from longbridge.openapi import QuoteContext, TradeContext

        from qresearch.brokers.longbridge.config import load_longbridge_config

        config = load_longbridge_config()
        return cls(
            trade_ctx=TradeContext(config),
            quote_ctx=QuoteContext(config),
            currency=currency,
            dry_run=dry_run,
            default_market=default_market,
            initial_cash=initial_cash,
        )

    def quantize_quantity(self, quantity: float) -> float:
        """Public lot/share quantize used by TargetWeightExecutor."""
        return float(self._quantize_qty(quantity))

    def submit_order(self, order: Order, *, price: float, timestamp: pd.Timestamp) -> Fill:
        symbol = normalize_symbol(order.symbol, default_market=self.default_market)
        qty = self._quantize_qty(order.quantity)
        if qty <= 0:
            order.status = OrderStatus.REJECTED
            raise ValueError(f"quantity too small after quantize: {order.quantity}")
        if price <= 0 or pd.isna(price):
            order.status = OrderStatus.REJECTED
            raise ValueError(f"invalid price for {symbol}: {price}")

        if self.dry_run:
            fill = self._dry_run_fill(order, symbol=symbol, qty=float(qty), price=float(price), timestamp=timestamp)
            order.status = OrderStatus.FILLED
            self.fill_log.append(fill)
            return fill

        assert self.trade_ctx is not None
        from longbridge.openapi import (
            OrderSide as LBSide,
            OrderType as LBType,
            TimeInForceType,
        )

        lb_side = LBSide.Buy if order.side == OrderSide.BUY else LBSide.Sell
        remark = f"{self.remark_prefix}:{order.client_order_id}"[:64]

        if order.order_type == OrderType.LIMIT:
            lim = order.limit_price if order.limit_price is not None else price
            resp = self.trade_ctx.submit_order(
                symbol=symbol,
                order_type=LBType.LO,
                side=lb_side,
                submitted_quantity=qty,
                time_in_force=TimeInForceType.Day,
                submitted_price=Decimal(str(lim)),
                remark=remark,
                client_request_id=order.client_order_id,
            )
        else:
            resp = self.trade_ctx.submit_order(
                symbol=symbol,
                order_type=LBType.MO,
                side=lb_side,
                submitted_quantity=qty,
                time_in_force=TimeInForceType.Day,
                remark=remark,
                client_request_id=order.client_order_id,
            )

        order_id = str(getattr(resp, "order_id", resp))
        fill_price, fill_qty, fee = self._await_fill(
            order_id, fallback_price=float(price), fallback_qty=float(qty)
        )
        order.status = OrderStatus.FILLED
        fill = Fill(
            order_id=order_id,
            symbol=symbol,
            side=order.side,
            quantity=fill_qty,
            price=fill_price,
            fee=fee,
            timestamp=pd.Timestamp(timestamp),
        )
        self.fill_log.append(fill)
        return fill

    def cancel_order(self, order_id: str) -> None:
        if self.dry_run or self.trade_ctx is None:
            return
        self.trade_ctx.cancel_order(order_id)

    def get_positions(self) -> dict[str, float]:
        if self.trade_ctx is None:
            return dict(self._local_positions)
        resp = self.trade_ctx.stock_positions()
        out: dict[str, float] = {}
        channels = getattr(resp, "channels", None) or []
        for ch in channels:
            for pos in getattr(ch, "positions", None) or []:
                sym = normalize_symbol(pos.symbol, default_market=self.default_market)
                out[sym] = out.get(sym, 0.0) + float(pos.quantity)
        return out

    def get_cash(self) -> float:
        if self.trade_ctx is None:
            return float(self._local_cash)
        balances = self.trade_ctx.account_balance()
        items = balances if isinstance(balances, (list, tuple)) else [balances]
        for bal in items:
            for info in getattr(bal, "cash_infos", None) or []:
                if str(getattr(info, "currency", "")).upper() == self.currency.upper():
                    return float(info.available_cash)
            if str(getattr(bal, "currency", "")).upper() == self.currency.upper():
                return float(getattr(bal, "total_cash", 0.0))
        if items:
            bal = items[0]
            cash_infos = getattr(bal, "cash_infos", None) or []
            if cash_infos:
                return float(cash_infos[0].available_cash)
            return float(getattr(bal, "total_cash", 0.0))
        return 0.0

    def get_equity(self, marks: dict[str, float]) -> float:
        if self.trade_ctx is not None:
            balances = self.trade_ctx.account_balance()
            items = balances if isinstance(balances, (list, tuple)) else [balances]
            for bal in items:
                if str(getattr(bal, "currency", "")).upper() == self.currency.upper():
                    net = getattr(bal, "net_assets", None)
                    if net is not None:
                        return float(net)

        cash = self.get_cash()
        equity = cash
        for sym, qty in self.get_positions().items():
            px = marks.get(sym, marks.get(sym.upper()))
            if px is None or pd.isna(px):
                continue
            equity += float(qty) * float(px)
        return float(equity)

    def fills(self) -> list[Fill]:
        return list(self.fill_log)

    def _dry_run_fill(
        self,
        order: Order,
        *,
        symbol: str,
        qty: float,
        price: float,
        timestamp: pd.Timestamp,
    ) -> Fill:
        notional = qty * price
        if self.trade_ctx is None:
            signed = qty if order.side == OrderSide.BUY else -qty
            if order.side == OrderSide.BUY:
                if notional > self._local_cash + 1e-9:
                    order.status = OrderStatus.REJECTED
                    raise ValueError("dry-run insufficient cash")
                self._local_cash -= notional
            else:
                self._local_cash += notional
            self._local_positions[symbol] = self._local_positions.get(symbol, 0.0) + signed
            if abs(self._local_positions[symbol]) < 1e-12:
                self._local_positions.pop(symbol, None)
        return Fill(
            order_id=f"dry-{order.client_order_id}",
            symbol=symbol,
            side=order.side,
            quantity=qty,
            price=price,
            fee=0.0,
            timestamp=pd.Timestamp(timestamp),
        )

    def _quantize_qty(self, quantity: float) -> Decimal:
        q = Decimal(str(quantity))
        if self.quantity_decimals <= 0:
            return q.to_integral_value(rounding=ROUND_DOWN)
        quant = Decimal("1").scaleb(-self.quantity_decimals)
        return q.quantize(quant, rounding=ROUND_DOWN)

    def _await_fill(
        self,
        order_id: str,
        *,
        fallback_price: float,
        fallback_qty: float,
    ) -> tuple[float, float, float]:
        assert self.trade_ctx is not None
        from longbridge.openapi import OrderStatus as LBStatus

        for _ in range(max(self.poll_fills, 1)):
            try:
                detail = self.trade_ctx.order_detail(order_id=order_id)
            except TypeError:
                detail = self.trade_ctx.order_detail(order_id)
            status = getattr(detail, "status", None)
            exe_qty = float(getattr(detail, "executed_quantity", 0) or 0)
            exe_px = getattr(detail, "executed_price", None)
            if status in (LBStatus.Filled, LBStatus.PartialFilled) and exe_qty > 0:
                px = float(exe_px) if exe_px not in (None, "") else float(fallback_price)
                return px, exe_qty, 0.0
            if status in (LBStatus.Rejected, LBStatus.Canceled, LBStatus.Expired):
                raise RuntimeError(f"Longbridge order {order_id} ended with status={status}")
            time.sleep(self.poll_interval_sec)
        return float(fallback_price), float(fallback_qty), 0.0
