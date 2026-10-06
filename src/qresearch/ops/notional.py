"""Sleeve Notional = min(cap, equity) unless Buying-Power Cap is on.

``QRESEARCH_SLEEVE_USD=equity`` (also ``100%``, ``account``, ``all``, ``full``)
means the sleeve is 100% of account equity, with no dollar cap.
"""

from __future__ import annotations

_FULL_EQUITY = {"equity", "account", "all", "full", "100%"}


def resolve_sleeve_cap(raw: str | None, *, unset: float | None = None) -> float | None:
    """Dollar cap for the sleeve.

    ``None`` means no cap: size to 100% of the account base.
    A positive number is the operator cap. Zero or negative is returned as-is.
    """
    if raw is None:
        return unset
    text = raw.strip()
    if text == "":
        return unset
    if text.lower() in _FULL_EQUITY:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(
            "QRESEARCH_SLEEVE_USD must be a number or equity/100%/account"
        ) from exc


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
