"""Risk budgeting / portfolio allocation utilities."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RiskBudgetConfig:
    """Convert raw signals into target portfolio weights.

    Steps:
    1) Keep signal direction; long-only optional
    2) Weight active names by inverse volatility (or equal)
    3) Scale to target gross exposure / clip max weight
    4) Optional portfolio vol targeting via trailing cov
    """

    vol_lookback: int = 20
    invert_vol: bool = True
    target_gross: float = 1.0
    target_vol: float | None = None  # annualized, e.g. 0.10
    max_weight: float = 0.5
    allow_short: bool = False
    periods_per_year: int = 252
    eps: float = 1e-8


def allocate_risk_budget(
    signals: pd.DataFrame,
    closes: pd.DataFrame,
    config: RiskBudgetConfig | None = None,
) -> pd.DataFrame:
    """Map signal matrix → target weight matrix (same shape)."""
    cfg = config or RiskBudgetConfig()
    sig = signals.reindex(columns=closes.columns).astype(float).fillna(0.0)
    if not cfg.allow_short:
        sig = sig.clip(lower=0.0)

    active = sig.abs() > cfg.eps
    rets = closes.pct_change()
    vol = rets.rolling(cfg.vol_lookback, min_periods=cfg.vol_lookback).std()
    vol = vol.where(active)

    if cfg.invert_vol:
        score = (1.0 / vol.replace(0.0, np.nan)).fillna(0.0)
    else:
        score = active.astype(float)

    # Directional score
    directed = score * np.sign(sig)
    abs_sum = directed.abs().sum(axis=1)
    weights = directed.div(abs_sum.replace(0.0, np.nan), axis=0).fillna(0.0)

    weights = weights.clip(-cfg.max_weight, cfg.max_weight)
    gross = weights.abs().sum(axis=1).replace(0.0, np.nan)
    weights = weights.div(gross, axis=0).fillna(0.0) * cfg.target_gross

    # Warmup: no vol estimate ⇒ flat
    warmup = vol.isna().all(axis=1)
    weights = weights.where(~warmup, other=0.0)

    if cfg.target_vol is not None:
        weights = _apply_vol_target(weights, rets, cfg)

    return weights.fillna(0.0)


def _apply_vol_target(
    weights: pd.DataFrame,
    rets: pd.DataFrame,
    cfg: RiskBudgetConfig,
) -> pd.DataFrame:
    """Scale weights so trailing portfolio vol ≈ target_vol."""
    out = np.array(weights.to_numpy(dtype=float), copy=True)
    lookback = cfg.vol_lookback
    target_daily = cfg.target_vol / np.sqrt(cfg.periods_per_year)
    ret_arr = rets.to_numpy(dtype=float)
    idx_n = len(weights)

    for i in range(idx_n):
        w = out[i]
        if i < lookback or np.abs(w).sum() < cfg.eps:
            if i < lookback:
                out[i] = 0.0
            continue
        window = ret_arr[i - lookback : i]
        mask = ~np.isnan(window).any(axis=1)
        window = window[mask]
        if len(window) < max(5, lookback // 3):
            out[i] = 0.0
            continue
        cov = np.cov(window, rowvar=False)
        port_var = float(w @ cov @ w)
        port_vol = np.sqrt(max(port_var, 0.0))
        if port_vol < cfg.eps:
            continue
        scaled = w * (target_daily / port_vol)
        scaled = np.clip(scaled, -cfg.max_weight, cfg.max_weight)
        g = np.abs(scaled).sum()
        if g > cfg.target_gross + cfg.eps:
            scaled = scaled / g * cfg.target_gross
        out[i] = scaled

    return pd.DataFrame(out, index=weights.index, columns=weights.columns)
