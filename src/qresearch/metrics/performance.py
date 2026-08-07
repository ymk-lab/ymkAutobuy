"""Performance metrics for research evaluation."""

from __future__ import annotations

import numpy as np
import pandas as pd


def summarize_performance(
    *,
    returns: pd.Series,
    equity: pd.Series,
    turnover: pd.Series,
    positions: pd.Series,
    periods_per_year: int = 252,
) -> dict[str, float]:
    r = returns.fillna(0.0).astype(float)
    if len(r) == 0:
        return {
            "total_return": 0.0,
            "cagr": 0.0,
            "ann_vol": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "calmar": 0.0,
            "hit_rate": 0.0,
            "avg_turnover": 0.0,
            "avg_abs_position": 0.0,
            "n_bars": 0.0,
        }

    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0) if len(equity) else 0.0
    years = max(len(r) / periods_per_year, 1e-12)
    cagr = float((1.0 + total_return) ** (1.0 / years) - 1.0)
    ann_vol = float(r.std(ddof=0) * np.sqrt(periods_per_year))
    sharpe = float((r.mean() * periods_per_year) / ann_vol) if ann_vol > 1e-12 else 0.0

    roll_max = equity.cummax()
    dd = equity / roll_max - 1.0
    max_drawdown = float(dd.min()) if len(dd) else 0.0
    calmar = float(cagr / abs(max_drawdown)) if abs(max_drawdown) > 1e-12 else 0.0

    active = r[positions.abs() > 1e-12]
    hit_rate = float((active > 0).mean()) if len(active) else 0.0

    return {
        "total_return": total_return,
        "cagr": cagr,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "hit_rate": hit_rate,
        "avg_turnover": float(turnover.mean()),
        "avg_abs_position": float(positions.abs().mean()),
        "n_bars": float(len(r)),
    }
