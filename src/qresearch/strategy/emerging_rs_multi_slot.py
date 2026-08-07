"""Emerging RS multi-slot book: up to N names, capped dollars per name."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from qresearch.strategy.emerging_rs_wave import EmergingRSWaveConfig, GateId, market_gate


@dataclass
class EmergingRSMultiSlotConfig(EmergingRSWaveConfig):
    max_names: int = 10
    max_notional_usd: float = 5_000.0


@dataclass
class _Lot:
    shares: float
    peak: float
    half: bool = False


@dataclass
class EmergingRSMultiSlotBook:
    """Multi-name Emerging RS with per-name exits and capped entry notionals.

    Decisions are made on the close; the companion simulator executes on the
    next open. ``generate_targets`` returns desired share counts (not weights).
    """

    gate: GateId = "G1"
    config: EmergingRSMultiSlotConfig | None = None
    name: str = "emerging_rs_multi_slot"

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = EmergingRSMultiSlotConfig()

    def _signals(self, closes: pd.DataFrame, bench: pd.Series) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame]:
        cfg = self.config
        assert cfg is not None
        px = closes.astype(float)
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

        pos_s = excess_s > 0.0
        persist = pos_s.copy()
        for k in range(1, cfg.persist_days):
            persist = persist & pos_s.shift(k).fillna(False)
        just_turned = persist & pos_s.shift(cfg.persist_days).eq(False)
        entry_ok = just_turned & (excess_m > 0.0) & (excess_l <= cfg.already_strong_cap) & persist
        gate_on = market_gate(bench, self.gate).reindex(px.index).fillna(False)
        return entry_ok, gate_on, excess_s, sma


@dataclass
class MultiSlotSimResult:
    equity: pd.Series
    cash: pd.Series
    trades: pd.DataFrame
    events: pd.DataFrame
    holdings_count: pd.Series
    final_positions: dict[str, float]


def simulate_multi_slot(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    bench_close: pd.Series,
    *,
    capital: float = 50_000.0,
    gate: GateId = "G1",
    config: EmergingRSMultiSlotConfig | None = None,
    fees: object | None = None,
    start: pd.Timestamp | None = None,
) -> MultiSlotSimResult:
    """Next-open execution multi-slot Emerging RS backtest."""
    from qresearch.backtest.futu_costs import FutuUsEquityFees

    cfg = config or EmergingRSMultiSlotConfig()
    fee_model = fees if fees is not None else FutuUsEquityFees(slippage_bps=3.0)

    book = EmergingRSMultiSlotBook(gate=gate, config=cfg)
    px = closes.astype(float).sort_index()
    op = opens.astype(float).reindex(px.index)
    bench = bench_close.astype(float).reindex(px.index).ffill()
    entry_ok, gate_on, excess_s, sma = book._signals(px, bench)

    dates = list(px.index)
    if start is not None:
        start = pd.Timestamp(start)
        # Warm-up signals on full history; trade only from start.
    else:
        start = dates[0]

    cash = float(capital)
    lots: dict[str, _Lot] = {}
    # Pending orders decided at prior close, filled at today's open.
    pending_sells: dict[str, float] = {}  # symbol -> shares to sell
    pending_buys: list[str] = []  # symbols to buy (size at open)

    equity_rows: list[float] = []
    cash_rows: list[float] = []
    hold_rows: list[int] = []
    trades: list[dict] = []
    events: list[dict] = []

    for dt in dates:
        # --- 1) Execute pending from prior decision (evaluation window only) ---
        if dt >= start:
            for sym, sh in list(pending_sells.items()):
                if sym not in lots:
                    continue
                px_o = float(op.at[dt, sym]) if sym in op.columns else np.nan
                if not np.isfinite(px_o) or px_o <= 0:
                    continue
                lot = lots[sym]
                sell_sh = min(float(sh), lot.shares)
                if sell_sh <= 0:
                    continue
                notional = sell_sh * px_o
                cost = float(fee_model.total_cost_usd(notional, px_o))
                cash += notional - cost
                lot.shares -= sell_sh
                trades.append(
                    {
                        "date": dt.strftime("%Y-%m-%d"),
                        "side": "SELL",
                        "symbol": sym,
                        "shares": round(sell_sh, 4),
                        "price_open": round(px_o, 4),
                        "notional_usd": round(notional, 2),
                        "cost_usd": round(cost, 2),
                        "cash_after": round(cash, 2),
                    }
                )
                if lot.shares <= 1e-9:
                    lots.pop(sym, None)
            pending_sells.clear()

            for sym in pending_buys:
                if sym in lots:
                    continue
                if len(lots) >= cfg.max_names:
                    break
                px_o = float(op.at[dt, sym]) if sym in op.columns else np.nan
                if not np.isfinite(px_o) or px_o <= 0:
                    continue
                if px_o > cfg.max_notional_usd + 1e-9:
                    continue
                budget = min(cfg.max_notional_usd, cash)
                shares = float(np.floor(budget / px_o))
                if shares < 1:
                    continue
                notional = shares * px_o
                cost = float(fee_model.total_cost_usd(notional, px_o))
                if notional + cost > cash + 1e-9:
                    shares = float(np.floor((cash * 0.999) / px_o))
                    if shares < 1:
                        continue
                    notional = shares * px_o
                    cost = float(fee_model.total_cost_usd(notional, px_o))
                    if notional + cost > cash + 1e-9:
                        continue
                cash -= notional + cost
                peak0 = float(px.at[dt, sym])
                lots[sym] = _Lot(
                    shares=shares,
                    peak=peak0 if np.isfinite(peak0) else px_o,
                )
                trades.append(
                    {
                        "date": dt.strftime("%Y-%m-%d"),
                        "side": "BUY",
                        "symbol": sym,
                        "shares": round(shares, 4),
                        "price_open": round(px_o, 4),
                        "notional_usd": round(notional, 2),
                        "cost_usd": round(cost, 2),
                        "cash_after": round(cash, 2),
                    }
                )
            pending_buys = []

        # --- 2) Mark peaks / equity ---
        mtm = 0.0
        for sym, lot in lots.items():
            c = float(px.at[dt, sym]) if sym in px.columns else np.nan
            if np.isfinite(c):
                mtm += lot.shares * c
                if not np.isfinite(lot.peak) or c > lot.peak:
                    lot.peak = c
        if dt >= start:
            equity_rows.append(cash + mtm)
            cash_rows.append(cash)
            hold_rows.append(len(lots))

        # Before evaluation start: do not open/hold (flat-start).
        if dt < start:
            pending_sells = {}
            pending_buys = []
            lots.clear()
            cash = float(capital)
            continue

        # --- 3) Decide exits / entries for next open ---
        next_sells: dict[str, float] = {}
        for sym, lot in list(lots.items()):
            price = float(px.at[dt, sym])
            ex_s = float(excess_s.at[dt, sym]) if sym in excess_s.columns else np.nan
            ma = float(sma.at[dt, sym]) if sym in sma.columns else np.nan
            weak = (np.isfinite(ex_s) and ex_s < 0.0) or (
                np.isfinite(ma) and np.isfinite(price) and price < ma
            )
            dd = (
                (price / lot.peak - 1.0)
                if (np.isfinite(lot.peak) and lot.peak > 0 and np.isfinite(price))
                else 0.0
            )
            hard = dd <= -abs(cfg.peak_dd_stop)
            gate_off = not bool(gate_on.loc[dt])
            reason = None
            sell_shares = 0.0
            if hard or gate_off:
                sell_shares = lot.shares
                reason = "peak_dd_stop" if hard else "gate_off"
                lot.half = False
            elif weak:
                if cfg.weaken_goes_flat or lot.half:
                    sell_shares = lot.shares
                    reason = "weaken_flat"
                else:
                    sell_shares = float(np.floor(lot.shares / 2.0)) or lot.shares
                    if sell_shares >= lot.shares:
                        sell_shares = lot.shares
                        reason = "weaken_flat"
                    else:
                        reason = "weaken_to_half"
                        lot.half = True
            if sell_shares > 0:
                next_sells[sym] = sell_shares
                events.append(
                    {
                        "date": dt.strftime("%Y-%m-%d"),
                        "action": "EXIT" if sell_shares >= lot.shares - 1e-9 else "TRIM",
                        "symbol": sym,
                        "shares": sell_shares,
                        "reason": reason,
                        "excess_20": ex_s,
                        "peak_dd": dd,
                    }
                )

        held_after = set(lots) - {
            s for s, sh in next_sells.items() if sh >= lots[s].shares - 1e-9
        }
        slots = cfg.max_names - len(held_after)
        free_cash = cash
        for sym, sh in next_sells.items():
            c = float(px.at[dt, sym])
            if np.isfinite(c):
                free_cash += sh * c

        next_buys: list[str] = []
        if slots > 0 and bool(gate_on.loc[dt]) and free_cash >= 1.0:
            row_ok = entry_ok.loc[dt]
            scored: list[tuple[float, str]] = []
            for s in px.columns:
                if s in held_after or s in next_sells:
                    continue
                if not bool(row_ok.get(s, False)):
                    continue
                v = float(excess_s.at[dt, s])
                c = float(px.at[dt, s])
                if not np.isfinite(v) or not np.isfinite(c) or c <= 0:
                    continue
                if c > cfg.max_notional_usd + 1e-9:
                    continue
                scored.append((v, s))
            scored.sort(key=lambda x: (-x[0], x[1]))
            reserved = 0.0
            for v, s in scored:
                if len(next_buys) >= slots:
                    break
                need = min(cfg.max_notional_usd, free_cash - reserved)
                if need < float(px.at[dt, s]):
                    continue
                next_buys.append(s)
                reserved += cfg.max_notional_usd
                events.append(
                    {
                        "date": dt.strftime("%Y-%m-%d"),
                        "action": "ENTER",
                        "symbol": s,
                        "shares": np.nan,
                        "reason": "emerging_rs",
                        "excess_20": v,
                        "peak_dd": 0.0,
                        "n_candidates": len(scored),
                    }
                )

        pending_sells = next_sells
        pending_buys = next_buys

    idx = pd.DatetimeIndex([d for d in dates if d >= start][: len(equity_rows)])
    eq = pd.Series(equity_rows, index=idx, name="equity")
    cash_s = pd.Series(cash_rows, index=idx, name="cash")
    hc = pd.Series(hold_rows, index=idx, name="n_holdings")
    return MultiSlotSimResult(
        equity=eq,
        cash=cash_s,
        trades=pd.DataFrame(trades),
        events=pd.DataFrame(events),
        holdings_count=hc,
        final_positions={s: lot.shares for s, lot in lots.items()},
    )
