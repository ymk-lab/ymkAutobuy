"""Transaction cost models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    """Simple proportional cost model.

    total_cost_rate ≈ fee_bps + slippage_bps, applied on traded notional.
    """

    fee_bps: float = 1.0
    slippage_bps: float = 2.0

    def cost_rate(self) -> float:
        return (self.fee_bps + self.slippage_bps) / 10_000.0

    def trade_cost(self, traded_notional: float) -> float:
        return abs(traded_notional) * self.cost_rate()
