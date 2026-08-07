"""Broker adapter interface (paper / sim / future live venues)."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from qresearch.execution.types import Fill, Order


class BrokerAdapter(ABC):
    """Minimal execution port used by the live loop.

    Concrete adapters may paper-trade, simulate, or route to a real venue.
    """

    @abstractmethod
    def submit_order(self, order: Order, *, price: float, timestamp: pd.Timestamp) -> Fill:
        """Submit and (for research adapters) immediately fill an order."""

    @abstractmethod
    def get_positions(self) -> dict[str, float]:
        """Return share/unit quantities by symbol."""

    @abstractmethod
    def get_cash(self) -> float:
        """Return free cash balance."""

    @abstractmethod
    def get_equity(self, marks: dict[str, float]) -> float:
        """Mark-to-market equity using provided prices."""

    def cancel_order(self, order_id: str) -> None:
        """Optional cancel; default no-op for immediate-fill adapters."""
        del order_id

    def fills(self) -> list[Fill]:
        """Optional fill history."""
        return []
