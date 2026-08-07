"""Futu (富途牛牛) US equity/ETF fee helpers for research-live parity."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FutuUsEquityFees:
    """Futu HK fixed US stock/ETF schedule (approx; confirm in app before live).

    - Commission: $0.0049/share, min $0.99/order
    - Platform:   $0.005/share,  min $1.00/order
    - Clearance:  $0.003/share
    - Commission+platform capped at 0.5% of notional, but not below the order mins
    - Slippage: separate bps on traded notional
    """

    commission_per_share: float = 0.0049
    commission_min: float = 0.99
    platform_per_share: float = 0.005
    platform_min: float = 1.00
    clearance_per_share: float = 0.003
    slippage_bps: float = 3.0
    broker_fee_cap_rate: float = 0.005

    def broker_fee_usd(self, shares: float, notional: float) -> float:
        shares = abs(float(shares))
        notional = abs(float(notional))
        if shares <= 0 or notional <= 0:
            return 0.0
        commission = max(self.commission_min, shares * self.commission_per_share)
        platform = max(self.platform_min, shares * self.platform_per_share)
        combined = commission + platform
        mins = self.commission_min + self.platform_min
        capped = max(notional * self.broker_fee_cap_rate, mins)
        combined = min(combined, capped)
        clearance = shares * self.clearance_per_share
        return combined + clearance

    def total_cost_usd(self, traded_notional: float, price: float) -> float:
        notional = abs(float(traded_notional))
        if notional <= 0 or price <= 0:
            return 0.0
        shares = notional / float(price)
        broker = self.broker_fee_usd(shares, notional)
        slip = notional * (self.slippage_bps / 10_000.0)
        return broker + slip

    def cost_return_on_equity(
        self, turnover_weight: float, equity: float, price: float
    ) -> float:
        if equity <= 0:
            return 0.0
        traded_notional = abs(float(turnover_weight)) * float(equity)
        return self.total_cost_usd(traded_notional, price) / float(equity)
