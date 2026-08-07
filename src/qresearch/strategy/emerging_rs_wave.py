"""Emerging Relative Strength wave book: single-name slot, staged exit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

GateId = Literal["G1", "G2", "G3", "G4"]


def market_gate(qqq_close: pd.Series, gate: GateId) -> pd.Series:
    """Return boolean Series: True when new entries are allowed."""
    c = qqq_close.astype(float)
    sma50 = c.rolling(50, min_periods=50).mean()
    sma200 = c.rolling(200, min_periods=200).mean()
    ret20 = c / c.shift(20) - 1.0
    g1 = c > sma50
    g2 = g1 & (sma50 > sma200)
    g3 = ret20 > 0.0
    g4 = g1 & g3
    table = {"G1": g1, "G2": g2, "G3": g3, "G4": g4}
    if gate not in table:
        raise ValueError(f"unknown gate {gate}")
    return table[gate].fillna(False)


@dataclass
class EmergingRSWaveConfig:
    short_window: int = 20
    mid_window: int = 10
    long_window: int = 60
    persist_days: int = 3
    already_strong_cap: float = 0.10
    exit_ma: int = 50
    peak_dd_stop: float = 0.10
    entry_weight: float = 1.0
    half_weight: float = 0.50


@dataclass
class EmergingRSWaveBook:
    """Single-name Emerging RS book decided at the close.

    Emits a weight matrix (dates × symbols) of *decision* weights; the
    backtester should shift by one bar for next-open execution.
    """

    gate: GateId = "G1"
    config: EmergingRSWaveConfig | None = None
    name: str = "emerging_rs_wave"

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = EmergingRSWaveConfig()

    def generate_weights(
        self,
        closes: pd.DataFrame,
        qqq_close: pd.Series,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return (weights, event_log).

        ``closes`` columns are symbols; index is trading dates aligned.
        """
        cfg = self.config
        assert cfg is not None
        px = closes.astype(float).sort_index()
        bench = qqq_close.astype(float).reindex(px.index).ffill()
        gate_on = market_gate(bench, self.gate).reindex(px.index).fillna(False)

        stock_ret_s = px / px.shift(cfg.short_window) - 1.0
        stock_ret_m = px / px.shift(cfg.mid_window) - 1.0
        stock_ret_l = px / px.shift(cfg.long_window) - 1.0
        bench_s = bench / bench.shift(cfg.short_window) - 1.0
        bench_m = bench / bench.shift(cfg.mid_window) - 1.0
        bench_l = bench / bench.shift(cfg.long_window) - 1.0
        excess_s = stock_ret_s.sub(bench_s, axis=0)
        excess_m = stock_ret_m.sub(bench_m, axis=0)
        excess_l = stock_ret_l.sub(bench_l, axis=0)
        sma = px.rolling(cfg.exit_ma, min_periods=cfg.exit_ma).mean()

        # Persistence: last persist_days all have short excess > 0
        pos_s = excess_s > 0.0
        persist = pos_s.copy()
        for k in range(1, cfg.persist_days):
            persist = persist & pos_s.shift(k).fillna(False)
        # Just turned: day before the streak was not positive
        prior_pos = pos_s.shift(cfg.persist_days)
        just_turned = persist & prior_pos.eq(False)
        mid_ok = excess_m > 0.0
        not_already = excess_l <= cfg.already_strong_cap
        entry_ok = just_turned & mid_ok & not_already & persist

        symbols = list(px.columns)
        dates = list(px.index)
        weights = pd.DataFrame(0.0, index=px.index, columns=symbols)
        events: list[dict] = []

        held: str | None = None
        w = 0.0
        peak = np.nan

        for i, dt in enumerate(dates):
            if held is not None:
                price = float(px.at[dt, held])
                if np.isfinite(price):
                    if not np.isfinite(peak) or price > peak:
                        peak = price
                # exit checks
                ex_s = float(excess_s.at[dt, held]) if held in excess_s.columns else np.nan
                ma = float(sma.at[dt, held]) if held in sma.columns else np.nan
                weak = (np.isfinite(ex_s) and ex_s < 0.0) or (
                    np.isfinite(ma) and np.isfinite(price) and price < ma
                )
                dd = (price / peak - 1.0) if (np.isfinite(peak) and peak > 0 and np.isfinite(price)) else 0.0
                hard = dd <= -abs(cfg.peak_dd_stop)
                gate_off = not bool(gate_on.iloc[i])

                new_w = w
                reason = None
                if hard or gate_off:
                    new_w = 0.0
                    reason = "peak_dd_stop" if hard else "gate_off"
                elif weak:
                    if w >= cfg.entry_weight - 1e-12:
                        new_w = cfg.half_weight
                        reason = "weaken_to_half"
                    else:
                        new_w = 0.0
                        reason = "weaken_flat"

                if new_w != w:
                    events.append(
                        {
                            "date": dt,
                            "action": "EXIT" if new_w == 0.0 else "TRIM",
                            "symbol": held,
                            "weight_from": w,
                            "weight_to": new_w,
                            "reason": reason,
                            "excess_20": ex_s,
                            "peak_dd": dd,
                        }
                    )
                    w = new_w
                    if w == 0.0:
                        held = None
                        peak = np.nan

            if held is None and bool(gate_on.iloc[i]):
                row_ok = entry_ok.iloc[i]
                candidates = [s for s in symbols if bool(row_ok.get(s, False))]
                # require finite excess for ranking
                scored: list[tuple[float, str]] = []
                for s in candidates:
                    v = float(excess_s.at[dt, s])
                    if np.isfinite(v):
                        scored.append((v, s))
                if scored:
                    scored.sort(key=lambda x: (-x[0], x[1]))
                    pick = scored[0][1]
                    held = pick
                    w = cfg.entry_weight
                    peak = float(px.at[dt, pick])
                    events.append(
                        {
                            "date": dt,
                            "action": "ENTER",
                            "symbol": pick,
                            "weight_from": 0.0,
                            "weight_to": w,
                            "reason": "emerging_rs",
                            "excess_20": scored[0][0],
                            "peak_dd": 0.0,
                            "n_candidates": len(scored),
                        }
                    )

            if held is not None:
                weights.at[dt, held] = w

        log = pd.DataFrame(events)
        return weights, log
