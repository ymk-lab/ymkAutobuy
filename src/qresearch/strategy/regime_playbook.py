"""Regime-switch portfolio: map Market Regime Label → playbooks (ADR-0009)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from qresearch.strategy.emerging_rs_wave import EmergingRSWaveBook, EmergingRSWaveConfig
from qresearch.strategy.regime_label import RegimeLabel, RegimeScorecardConfig, label_regimes


@dataclass
class RegimePlaybookConfig:
    panic_qqq_weight: float = 0.30  # PanicRebound sleeve weight in bench ETF
    ers_config: EmergingRSWaveConfig | None = None
    scorecard: RegimeScorecardConfig | None = None
    label_method: str = "scorecard"  # or "hierarchy"
    bench_symbol: str = "QQQ"  # CrowdedTrend / PanicRebound vehicle


@dataclass
class SwitchSimResult:
    equity: pd.Series
    labels: pd.Series
    raw_labels: pd.Series
    scores: pd.DataFrame
    meta: pd.DataFrame
    trades: pd.DataFrame
    mode: pd.Series  # cash / ers / bench / wind_down


def _active_symbol(weights_row: pd.Series) -> tuple[str | None, float]:
    active = weights_row[weights_row.abs() > 1e-12]
    if len(active) == 0:
        return None, 0.0
    return str(active.index[0]), float(active.iloc[0])


def simulate_regime_switch(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    qqq_open: pd.Series,
    qqq_close: pd.Series,
    *,
    capital: float = 50_000.0,
    start: pd.Timestamp | None = None,
    fees: object | None = None,
    config: RegimePlaybookConfig | None = None,
    bench_symbol: str | None = None,
) -> SwitchSimResult:
    """Next-open execution of label→playbook switching book.

    ``qqq_open`` / ``qqq_close`` are the *benchmark* series used for labels,
    G1 gate / RS, and CrowdedTrend / PanicRebound sleeves (historically QQQ;
    pass SMH for semiconductor book experiments).
    """
    from qresearch.backtest.futu_costs import FutuUsEquityFees

    cfg = config or RegimePlaybookConfig()
    fee_model = fees if fees is not None else FutuUsEquityFees(slippage_bps=3.0)
    ers_cfg = cfg.ers_config or EmergingRSWaveConfig()
    bench = (bench_symbol or cfg.bench_symbol or "QQQ").upper()

    labels, scores, meta = label_regimes(
        qqq_close,
        closes,
        config=cfg.scorecard,
        method=cfg.label_method,
    )
    book = EmergingRSWaveBook(gate="G1", config=ers_cfg)
    ers_w, _ers_log = book.generate_weights(closes, qqq_close)

    px = closes.astype(float).sort_index()
    op = opens.astype(float).reindex(px.index)
    qo = qqq_open.astype(float).reindex(px.index)
    qc = qqq_close.astype(float).reindex(px.index)
    lab = labels.reindex(px.index).fillna("Defense")
    ers_w = ers_w.reindex(px.index).fillna(0.0)

    dates = list(px.index)
    if start is None:
        start = dates[0]
    else:
        start = pd.Timestamp(start)

    cash = float(capital)
    # Position: either empty, or single name shares, or bench ETF shares
    pos_sym: str | None = None  # ticker or bench symbol
    pos_shares = 0.0
    pos_kind: str = "cash"  # cash|ers|bench
    target_sym: str | None = None
    target_w = 0.0

    equity_rows: list[float] = []
    mode_rows: list[str] = []
    trades: list[dict] = []
    eq_index: list[pd.Timestamp] = []

    def _mark(dt: pd.Timestamp) -> float:
        if pos_sym is None or pos_shares <= 0:
            return cash
        if pos_sym == bench:
            return cash + pos_shares * float(qc.at[dt])
        return cash + pos_shares * float(px.at[dt, pos_sym])

    def _sell_all(dt: pd.Timestamp, reason: str) -> None:
        nonlocal cash, pos_sym, pos_shares, pos_kind
        if pos_sym is None or pos_shares <= 0:
            return
        if pos_sym == bench:
            px_o = float(qo.at[dt])
        else:
            px_o = float(op.at[dt, pos_sym])
        if not np.isfinite(px_o) or px_o <= 0:
            return
        notional = pos_shares * px_o
        cost = float(fee_model.total_cost_usd(notional, px_o))
        cash += notional - cost
        trades.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "side": "SELL",
                "symbol": pos_sym,
                "shares": round(pos_shares, 4),
                "price": round(px_o, 4),
                "notional_usd": round(notional, 2),
                "cost_usd": round(cost, 2),
                "reason": reason,
            }
        )
        pos_sym, pos_shares, pos_kind = None, 0.0, "cash"

    def _buy_bench(dt: pd.Timestamp, weight: float, reason: str) -> None:
        nonlocal cash, pos_sym, pos_shares, pos_kind
        px_o = float(qo.at[dt])
        if not np.isfinite(px_o) or px_o <= 0:
            return
        equity = cash  # flat before buy
        budget = max(0.0, equity * weight)
        shares = float(np.floor(budget / px_o))
        if shares < 1:
            return
        notional = shares * px_o
        cost = float(fee_model.total_cost_usd(notional, px_o))
        if notional + cost > cash:
            shares = float(np.floor((cash * 0.999) / px_o))
            if shares < 1:
                return
            notional = shares * px_o
            cost = float(fee_model.total_cost_usd(notional, px_o))
        cash -= notional + cost
        pos_sym, pos_shares, pos_kind = bench, shares, "bench"
        trades.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "side": "BUY",
                "symbol": bench,
                "shares": round(shares, 4),
                "price": round(px_o, 4),
                "notional_usd": round(notional, 2),
                "cost_usd": round(cost, 2),
                "reason": reason,
            }
        )

    def _buy_ers(dt: pd.Timestamp, sym: str, weight: float, reason: str) -> None:
        nonlocal cash, pos_sym, pos_shares, pos_kind
        px_o = float(op.at[dt, sym])
        if not np.isfinite(px_o) or px_o <= 0:
            return
        budget = max(0.0, cash * abs(weight))
        shares = float(np.floor(budget / px_o))
        if shares < 1:
            return
        notional = shares * px_o
        cost = float(fee_model.total_cost_usd(notional, px_o))
        if notional + cost > cash:
            shares = float(np.floor((cash * 0.999) / px_o))
            if shares < 1:
                return
            notional = shares * px_o
            cost = float(fee_model.total_cost_usd(notional, px_o))
        cash -= notional + cost
        pos_sym, pos_shares, pos_kind = sym, shares, "ers"
        trades.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "side": "BUY",
                "symbol": sym,
                "shares": round(shares, 4),
                "price": round(px_o, 4),
                "notional_usd": round(notional, 2),
                "cost_usd": round(cost, 2),
                "reason": reason,
            }
        )

    def _trim_ers(dt: pd.Timestamp, to_weight: float, reason: str) -> None:
        """Trim ERS position toward to_weight of current equity (approx)."""
        nonlocal cash, pos_sym, pos_shares, pos_kind
        if pos_kind != "ers" or pos_sym is None:
            return
        px_o = float(op.at[dt, pos_sym])
        if not np.isfinite(px_o) or px_o <= 0:
            return
        equity = cash + pos_shares * px_o
        target_shares = float(np.floor((equity * to_weight) / px_o))
        sell = pos_shares - target_shares
        if sell <= 0:
            return
        notional = sell * px_o
        cost = float(fee_model.total_cost_usd(notional, px_o))
        cash += notional - cost
        pos_shares -= sell
        trades.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "side": "SELL",
                "symbol": pos_sym,
                "shares": round(sell, 4),
                "price": round(px_o, 4),
                "notional_usd": round(notional, 2),
                "cost_usd": round(cost, 2),
                "reason": reason,
            }
        )
        if pos_shares <= 1e-9:
            pos_sym, pos_shares, pos_kind = None, 0.0, "cash"

    def desired_from_label(label: str) -> tuple[str, float]:
        if label == "Defense":
            return "cash", 0.0
        if label == "CrowdedTrend":
            return "bench_full", 1.0
        if label == "PanicRebound":
            return "bench_panic", cfg.panic_qqq_weight
        if label == "Rotation":
            return "ers", 1.0
        if label == "Range":
            return "range", 0.0
        return "cash", 0.0

    pending_mode = "cash"
    pending_w = 0.0

    for dt in dates:
        if dt >= start:
            # Execute pending from prior close
            if pending_mode == "cash":
                _sell_all(dt, "to_cash")
            elif pending_mode in ("bench_full", "bench_panic", "qqq_full", "qqq_panic"):
                want_w = (
                    1.0
                    if pending_mode in ("bench_full", "qqq_full")
                    else cfg.panic_qqq_weight
                )
                if pos_kind == "ers":
                    _sell_all(dt, f"switch_to_{bench.lower()}")
                if pos_kind == "bench" and pos_sym == bench:
                    eq_now = cash + pos_shares * float(qo.at[dt])
                    cur_w = (pos_shares * float(qo.at[dt])) / eq_now if eq_now > 0 else 0
                    if abs(cur_w - want_w) > 0.15:
                        _sell_all(dt, f"rebalance_{bench.lower()}")
                        _buy_bench(dt, want_w, pending_mode)
                elif pos_kind == "cash":
                    _buy_bench(dt, want_w, pending_mode)
            elif pending_mode == "ers":
                if pos_kind == "bench":
                    _sell_all(dt, "switch_to_ers")
                sym, w = target_sym, target_w
                if sym is None or w <= 0:
                    if pos_kind == "ers":
                        _sell_all(dt, "ers_flat")
                else:
                    if pos_kind == "ers" and pos_sym != sym:
                        _sell_all(dt, "ers_rotate")
                    if pos_kind == "cash":
                        _buy_ers(dt, sym, w, "ers_enter")
                    elif pos_kind == "ers" and pos_sym == sym:
                        eq_now = cash + pos_shares * float(op.at[dt, sym])
                        cur_w = (pos_shares * float(op.at[dt, sym])) / eq_now if eq_now > 0 else 0
                        if w <= 0.6 and cur_w > 0.7:
                            _trim_ers(dt, 0.5, "ers_half")
                        elif w >= 0.9 and cur_w < 0.7:
                            _sell_all(dt, "ers_refull_sell")
                            _buy_ers(dt, sym, 1.0, "ers_refull_buy")
            elif pending_mode == "range":
                pass

            eq_index.append(dt)
            equity_rows.append(_mark(dt))
            mode_rows.append(pos_kind if pending_mode != "range" else f"range:{pos_kind}")

        # --- Decide for next open ---
        label = str(lab.at[dt])
        mode, wdesk = desired_from_label(label)

        if mode == "range":
            if pos_kind == "ers":
                sym, w = _active_symbol(ers_w.loc[dt])
                pending_mode = "ers"
                target_sym, target_w = sym, w
            elif pos_kind == "bench":
                sma50 = qc.rolling(50, min_periods=50).mean()
                if np.isfinite(float(sma50.at[dt])) and float(qc.at[dt]) < float(sma50.at[dt]):
                    pending_mode, target_sym, target_w = "cash", None, 0.0
                else:
                    pending_mode = "range"
                    target_sym, target_w = bench, 1.0 if pos_shares > 0 else 0.0
            else:
                pending_mode, target_sym, target_w = "cash", None, 0.0
        elif mode == "ers":
            sym, w = _active_symbol(ers_w.loc[dt])
            pending_mode = "ers"
            target_sym, target_w = sym, w
        elif mode == "bench_full":
            pending_mode, target_sym, target_w = "bench_full", bench, 1.0
        elif mode == "bench_panic":
            pending_mode, target_sym, target_w = "bench_panic", bench, cfg.panic_qqq_weight
        else:
            pending_mode, target_sym, target_w = "cash", None, 0.0

        if dt < start:
            cash = float(capital)
            pos_sym, pos_shares, pos_kind = None, 0.0, "cash"

    idx = pd.DatetimeIndex(eq_index)
    return SwitchSimResult(
        equity=pd.Series(equity_rows, index=idx, name="equity"),
        labels=lab.reindex(idx),
        raw_labels=meta["raw_label"].reindex(idx),
        scores=scores.reindex(idx),
        meta=meta.reindex(idx),
        trades=pd.DataFrame(trades),
        mode=pd.Series(mode_rows, index=idx, name="mode"),
    )


def simulate_bench_bh(
    bench_open: pd.Series,
    bench_close: pd.Series,
    *,
    capital: float,
    start: pd.Timestamp,
    fees: object,
) -> pd.Series:
    from qresearch.backtest.futu_costs import FutuUsEquityFees

    fee_model = fees if fees is not None else FutuUsEquityFees(slippage_bps=3.0)
    qo = bench_open.astype(float).loc[start:]
    qc = bench_close.astype(float).loc[start:]
    px0 = float(qo.iloc[0])
    shares = float(np.floor(capital / px0))
    notional = shares * px0
    cost = float(fee_model.total_cost_usd(notional, px0))
    cash = capital - notional - cost
    eq = cash + shares * qc
    eq.name = "equity"
    return eq


def simulate_qqq_bh(
    qqq_open: pd.Series,
    qqq_close: pd.Series,
    *,
    capital: float,
    start: pd.Timestamp,
    fees: object,
) -> pd.Series:
    """Alias for simulate_bench_bh (historical QQQ naming)."""
    return simulate_bench_bh(
        qqq_open, qqq_close, capital=capital, start=start, fees=fees
    )


def simulate_cash(*, capital: float, index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(capital, index=index, name="equity")
