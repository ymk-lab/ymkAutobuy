"""Sleeve Notional = min(cap, equity) unless Buying-Power Cap is on."""

from __future__ import annotations


def sleeve_notional(
    *,
    cap: float | None,
    equity: float,
    buying_power: float | None = None,
    buying_power_cap: bool = False,
) -> float:
    """Return the dollar base used to size the Production Book.

    Default: min(cap, equity). With buying_power_cap, equity is replaced by
    buying_power when that figure is available and positive.
    """
    eq = float(equity)
    if eq < 0:
        eq = 0.0
    base = eq
    if buying_power_cap:
        bp = float(buying_power) if buying_power is not None else eq
        if bp > 0:
            base = bp
    if cap is None:
        return base
    cap_f = float(cap)
    if cap_f <= 0:
        return 0.0
    return min(cap_f, base)
