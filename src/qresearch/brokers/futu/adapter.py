"""Futu OpenD BrokerAdapter (paper / SIMULATE by default)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Any

import pandas as pd

from qresearch.brokers.futu.config import (
    futu_opend_host,
    futu_opend_port,
    futu_trd_env_simulate,
    load_dotenv_if_present,
)
from qresearch.brokers.futu.symbols import normalize_symbol, to_futu_code
from qresearch.execution.adapter import BrokerAdapter
from qresearch.execution.types import Fill, Order, OrderSide, OrderStatus, OrderType


@dataclass
class FutuBrokerAdapter(BrokerAdapter):
    """Route research orders to Futu OpenD.

    Safety:
    - Default ``trd_env=SIMULATE`` (paper). Refuse REAL unless
      ``QRESEARCH_FUTU_ALLOW_LIVE=1`` and ``FUTU_TRD_ENV=REAL``.
    - ``dry_run=True`` never calls ``place_order``.
    """

    quote_ctx: Any = None
    trade_ctx: Any = None
    currency: str = "USD"
    dry_run: bool = True
    simulate: bool = True
    default_market: str = "US"
    acc_id: int = 0
    remark_prefix: str = "qresearch"
    initial_cash: float = 100_000.0
    # SIMULATE/US market orders can sit briefly; short polls caused false timeouts
    # after the first leg filled (e.g. QQQ ok, SPY aborted).
    poll_fills: int = 40
    poll_interval_sec: float = 0.5
    fills_log: list[Fill] = field(default_factory=list)
    _local_cash: float = field(init=False, repr=False)
    _local_positions: dict[str, float] = field(init=False, repr=False, default_factory=dict)
    _owns_ctx: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        if self.trade_ctx is None and not self.dry_run:
            raise ValueError("trade_ctx is required when dry_run=False")
        if not self.simulate:
            import os

            if os.getenv("QRESEARCH_FUTU_ALLOW_LIVE", "0").strip() not in {
                "1",
                "true",
                "yes",
                "on",
            }:
                raise ValueError(
                    "REFUSE live Futu trading: set QRESEARCH_FUTU_ALLOW_LIVE=1 "
                    "and FUTU_TRD_ENV=REAL only if you intend real orders"
                )
        self._local_cash = float(self.initial_cash)
        self._local_positions = {}

    @classmethod
    def from_opend(
        cls,
        *,
        dry_run: bool = True,
        currency: str = "USD",
        default_market: str = "US",
        initial_cash: float = 100_000.0,
        host: str | None = None,
        port: int | None = None,
        simulate: bool | None = None,
    ) -> "FutuBrokerAdapter":
        load_dotenv_if_present()
        from futu import OpenQuoteContext, OpenSecTradeContext, TrdMarket

        host = host or futu_opend_host()
        port = int(port or futu_opend_port())
        sim = futu_trd_env_simulate() if simulate is None else bool(simulate)
        quote_ctx = OpenQuoteContext(host=host, port=port)
        trade_ctx = OpenSecTradeContext(
            filter_trdmarket=TrdMarket.US,
            host=host,
            port=port,
        )
        adapter = cls(
            quote_ctx=quote_ctx,
            trade_ctx=trade_ctx,
            currency=currency,
            dry_run=dry_run,
            simulate=sim,
            default_market=default_market,
            initial_cash=initial_cash,
        )
        adapter._owns_ctx = True
        return adapter

    def close(self) -> None:
        if not self._owns_ctx:
            return
        for ctx in (self.quote_ctx, self.trade_ctx):
            if ctx is None:
                continue
            try:
                ctx.close()
            except Exception:
                pass

    def quantize_quantity(self, quantity: float) -> float:
        return float(self._quantize_qty(quantity))

    def _trd_env(self):
        from futu import TrdEnv

        return TrdEnv.SIMULATE if self.simulate else TrdEnv.REAL

    def submit_order(self, order: Order, *, price: float, timestamp: pd.Timestamp) -> Fill:
        symbol = normalize_symbol(order.symbol, default_market=self.default_market)
        qty = float(self._quantize_qty(order.quantity))
        if qty <= 0:
            order.status = OrderStatus.REJECTED
            raise ValueError(f"quantity too small after quantize: {order.quantity}")
        if price <= 0 or pd.isna(price):
            order.status = OrderStatus.REJECTED
            raise ValueError(f"invalid price for {symbol}: {price}")

        if self.dry_run:
            fill = self._dry_run_fill(
                order, symbol=symbol, qty=qty, price=float(price), timestamp=timestamp
            )
            order.status = OrderStatus.FILLED
            self.fills_log.append(fill)
            return fill

        assert self.trade_ctx is not None
        from futu import RET_OK, OrderType as FutuOrderType, TrdSide

        code = to_futu_code(symbol, default_market=self.default_market)
        side = TrdSide.BUY if order.side == OrderSide.BUY else TrdSide.SELL
        # MARKET still requires a price hint for US paper in Futu API.
        px = float(order.limit_price) if order.limit_price is not None else float(price)
        order_type = (
            FutuOrderType.NORMAL
            if order.order_type == OrderType.LIMIT
            else FutuOrderType.MARKET
        )
        remark = f"{self.remark_prefix}:{order.client_order_id}"[:64]
        ret, data = self.trade_ctx.place_order(
            price=px,
            qty=qty,
            code=code,
            trd_side=side,
            order_type=order_type,
            trd_env=self._trd_env(),
            acc_id=self.acc_id,
            remark=remark,
        )
        if ret != RET_OK:
            order.status = OrderStatus.REJECTED
            raise RuntimeError(f"futu place_order failed: {data}")

        order_id = str(data["order_id"].iloc[0])
        fill_price, fill_qty, fee = self._await_fill(
            order_id, fallback_price=float(price), fallback_qty=qty
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
        self.fills_log.append(fill)
        return fill

    def get_positions(self) -> dict[str, float]:
        if self.trade_ctx is None:
            return dict(self._local_positions)
        from futu import RET_OK

        ret, data = self.trade_ctx.position_list_query(trd_env=self._trd_env())
        if ret != RET_OK or data is None or len(data) == 0:
            return {}
        out: dict[str, float] = {}
        for _, row in data.iterrows():
            sym = normalize_symbol(str(row["code"]), default_market=self.default_market)
            qty = float(row.get("qty", 0) or 0)
            if abs(qty) < 1e-12:
                continue
            out[sym] = out.get(sym, 0.0) + qty
        return out

    def get_cash(self) -> float:
        if self.trade_ctx is None:
            return float(self._local_cash)
        from futu import RET_OK

        ret, data = self.trade_ctx.accinfo_query(trd_env=self._trd_env())
        if ret != RET_OK or data is None or len(data) == 0:
            return 0.0
        row = data.iloc[0]
        for key in ("us_cash", "cash", "avl_withdrawal_cash"):
            if key in row and row[key] is not None:
                try:
                    return float(row[key])
                except Exception:
                    continue
        return float(row.get("total_assets", 0) or 0)

    def get_equity(self, marks: dict[str, float]) -> float:
        if self.trade_ctx is not None:
            from futu import RET_OK

            ret, data = self.trade_ctx.accinfo_query(trd_env=self._trd_env())
            if ret == RET_OK and data is not None and len(data):
                row = data.iloc[0]
                for key in ("total_assets", "net_assets", "assets"):
                    if key in row and row[key] is not None:
                        try:
                            return float(row[key])
                        except Exception:
                            pass
        cash = self.get_cash()
        eq = cash
        for sym, qty in self.get_positions().items():
            px = marks.get(sym, marks.get(sym.upper()))
            if px is None or pd.isna(px):
                continue
            eq += float(qty) * float(px)
        return float(eq)

    def snapshot_quotes(self, symbols: list[str]) -> dict[str, float]:
        if self.quote_ctx is None or not symbols:
            return {}
        from futu import RET_OK

        codes = [to_futu_code(s, default_market=self.default_market) for s in symbols]
        ret, data = self.quote_ctx.get_market_snapshot(codes)
        if ret != RET_OK or data is None or len(data) == 0:
            return {}
        out: dict[str, float] = {}
        for _, row in data.iterrows():
            sym = normalize_symbol(str(row["code"]), default_market=self.default_market)
            last = row.get("last_price")
            if last is not None and float(last) > 0:
                out[sym] = float(last)
        return out

    def fills(self) -> list[Fill]:
        return list(self.fills_log)

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
        return q.to_integral_value(rounding=ROUND_DOWN)

    def _await_fill(
        self,
        order_id: str,
        *,
        fallback_price: float,
        fallback_qty: float,
    ) -> tuple[float, float, float]:
        assert self.trade_ctx is not None
        from futu import RET_OK

        last_status = ""
        last_dealt = 0.0
        for _ in range(max(self.poll_fills, 1)):
            ret, data = self.trade_ctx.order_list_query(
                order_id=order_id, trd_env=self._trd_env()
            )
            if ret == RET_OK and data is not None and len(data):
                row = data.iloc[0]
                status = str(row.get("order_status", "")).upper()
                dealt_qty = float(row.get("dealt_qty", 0) or 0)
                dealt_avg = row.get("dealt_avg_price")
                last_status, last_dealt = status, dealt_qty
                if dealt_qty > 0 and status in {
                    "FILLED_ALL",
                    "FILLED_PART",
                    "FILLED",
                    "COMPLETED",
                }:
                    px = float(dealt_avg) if dealt_avg not in (None, "") else fallback_price
                    return px, dealt_qty, 0.0
                if status in {
                    "CANCELLED_ALL",
                    "CANCELLED_PART",
                    "FAILED",
                    "DISABLED",
                    "DELETED",
                }:
                    raise RuntimeError(
                        f"futu order {order_id} ended unfilled "
                        f"(status={status}, dealt_qty={dealt_qty:g}, "
                        f"fallback_qty={fallback_qty:g})"
                    )
            time.sleep(self.poll_interval_sec)
        # Never invent a fill: doing so wrote phantom ledger rows while the
        # SIMULATE book stayed unchanged (looks like "duplicate buys").
        raise RuntimeError(
            f"futu order {order_id} not filled after poll "
            f"(status={last_status or 'unknown'}, dealt_qty={last_dealt:g}, "
            f"fallback_qty={fallback_qty:g} @ {fallback_price})"
        )
