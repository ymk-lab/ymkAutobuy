"""Order / fill primitives for broker adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

import pandas as pd


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    NEW = "new"
    SUBMITTED = "submitted"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


def _new_id() -> str:
    return uuid4().hex[:12]


@dataclass
class Order:
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    client_order_id: str = field(default_factory=_new_id)
    status: OrderStatus = OrderStatus.NEW
    created_at: pd.Timestamp | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("order quantity must be positive")
        self.symbol = str(self.symbol).upper()
        if isinstance(self.side, str):
            self.side = OrderSide(self.side)
        if isinstance(self.order_type, str):
            self.order_type = OrderType(self.order_type)


@dataclass(frozen=True)
class Fill:
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    fee: float
    timestamp: pd.Timestamp
