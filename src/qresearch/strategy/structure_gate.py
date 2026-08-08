"""Universe-agnostic Structure Gate: modes cash / ers / strong / bench.

Canonical names (code = docs):
- Modes: cash | ers | strong | bench
- Locus: stock_led | index_lean | neutral
- Sleeves: sticky | thrust | crowded
- Defense: mild | harsh
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

import numpy as np
import pandas as pd

from qresearch.strategy.emerging_rs_wave import EmergingRSWaveBook, EmergingRSWaveConfig
from qresearch.strategy.regime_label import RegimeScorecardConfig, score_regimes

StructureMode = Literal["cash", "ers", "strong", "bench"]


@dataclass
class StructureGateConfig:
    top_k_conc: int = 3
    top3_conc_min: float = 0.35
    crowded_overlap_min: float = 0.40
    strong_share_min: float = 0.30
    strong_overlap_min: float = 0.45
    ers_lag_lookback: int = 60
    ers_lag_trigger: float = -0.05  # ERS trailing sum excess vs bench
    # Already-strong leadership for strong mode
    already_strong_cap: float = 0.10
    strong_lookback: int = 60
    # Short trail (tactical stock_led / index_lean)
    leadership_trail_days: int = 20
    stock_led_min_trail: float = 0.02  # trail20 >= this → stock_led
    index_lean_max_trail: float = -0.03  # trail20 <= this → index_lean
    # Sticky sleeve: persist bench while leaders lag (long trail)
    sticky_trail_days: int = 60
    sticky_enter_trail: float = -0.05
    sticky_enter_confirm: int = 2
    sticky_exit_trail: float = -0.02
    sticky_exit_confirm: int = 5
    sticky_require_above50: bool = True
    sticky_require_ret20_pos: bool = False
    sticky_breadth_max: float = 0.40
    sticky_breadth_trail: float = -0.08
    sticky_exit_on_below50: bool = False
    sticky_forbid_stock_sleeves: bool = True
    # Thrust sleeve: absolute bench melt-up / recovery
    thrust_ret5_min: float = 0.04
    thrust_ret10_min: float = 0.07
    thrust_bounce20_min: float = 0.08  # close / 20d low - 1
    thrust_ret20_min: float = 0.10
    thrust_require_above50: bool = True
    thrust_confirm: int = 1
    thrust_overrides_dd_harsh: bool = True
    thrust_force_bench: bool = True
    # Mild defense
    mild_defense_dd: float = 0.08
    mild_defense_ret20: float = -0.03
    # Harsh defense
    harsh_defense_dd: float = 0.12
    harsh_defense_ret20: float = -0.08
    ers_config: EmergingRSWaveConfig | None = None


def top_concentration(ret_panel: pd.DataFrame, k: int = 3) -> pd.Series:
    """Share of positive cross-sectional return captured by top-k names."""

    def _row(row: pd.Series) -> float:
        s = row.replace([np.inf, -np.inf], np.nan).dropna()
        if len(s) < k:
            return float("nan")
        pos = s.clip(lower=0.0)
        tot = float(pos.sum())
        if tot <= 0:
            return 0.0
        return float(pos.nlargest(k).sum() / tot)

    return ret_panel.apply(_row, axis=1)


def structure_features(
    bench_close: pd.Series,
    member_closes: pd.DataFrame,
    *,
    config: StructureGateConfig | None = None,
) -> pd.DataFrame:
    cfg = config or StructureGateConfig()
    _scores, meta = score_regimes(
        bench_close, member_closes, config=RegimeScorecardConfig()
    )
    px = member_closes.astype(float).reindex(bench_close.index)
    r20 = px / px.shift(20) - 1.0
    conc = top_concentration(r20, k=cfg.top_k_conc)
    bc = bench_close.astype(float).reindex(px.index).ffill()
    stock60 = px / px.shift(60) - 1.0
    bench60 = bc / bc.shift(60) - 1.0
    pct_beat60 = stock60.gt(bench60, axis=0).sum(axis=1) / px.notna().sum(axis=1).clip(lower=1)
    low20 = bc.rolling(20, min_periods=5).min()
    bounce20 = bc / low20 - 1.0
    return pd.DataFrame(
        {
            "overlap": meta["overlap"],
            "strong_share": meta["strong_share"],
            "breadth": meta["breadth"],
            "above50": meta["above_sma50"],
            "ret20": meta["ret20"],
            "ret5": bc / bc.shift(5) - 1.0,
            "ret10": bc / bc.shift(10) - 1.0,
            "bounce20": bounce20,
            "dd60": meta["dd60"],
            "top3_conc20": conc,
            "pct_beat60": pct_beat60,
        },
        index=bench_close.index,
    )


def trailing_ers_excess(
    bench_close: pd.Series,
    member_closes: pd.DataFrame,
    *,
    config: StructureGateConfig | None = None,
) -> pd.Series:
    """Cost-free proxy: daily ERS book return minus bench, rolling sum."""
    cfg = config or StructureGateConfig()
    book = EmergingRSWaveBook(gate="G1", config=cfg.ers_config or EmergingRSWaveConfig())
    weights, _ = book.generate_weights(member_closes, bench_close)
    bc = bench_close.astype(float).sort_index()
    px = member_closes.astype(float).reindex(bc.index)
    w = weights.reindex(bc.index).fillna(0.0)

    ers_rets: list[float] = []
    for i, dt in enumerate(px.index):
        if i == 0:
            ers_rets.append(0.0)
            continue
        prev = px.index[i - 1]
        row = w.loc[prev]
        active = row[row.abs() > 1e-12]
        if len(active) == 0:
            ers_rets.append(0.0)
            continue
        sym = str(active.index[0])
        a = float(px.at[dt, sym]) if sym in px.columns else float("nan")
        b = float(px.at[prev, sym]) if sym in px.columns else float("nan")
        if not np.isfinite(a) or not np.isfinite(b) or b <= 0:
            ers_rets.append(0.0)
        else:
            ers_rets.append(a / b - 1.0)

    ers = pd.Series(ers_rets, index=px.index)
    bret = bc.pct_change().fillna(0.0)
    return (ers - bret).rolling(cfg.ers_lag_lookback, min_periods=20).sum()


def strong_leader_weights(
    member_closes: pd.DataFrame,
    bench_close: pd.Series,
    *,
    config: StructureGateConfig | None = None,
) -> pd.DataFrame:
    """Daily decision weights: 100% in the strongest already-strong name."""
    cfg = config or StructureGateConfig()
    px = member_closes.astype(float).sort_index()
    bench = bench_close.astype(float).reindex(px.index).ffill()
    lb = cfg.strong_lookback
    stock_ret = px / px.shift(lb) - 1.0
    bench_ret = bench / bench.shift(lb) - 1.0
    excess = stock_ret.sub(bench_ret, axis=0)

    weights = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for dt in px.index:
        row = excess.loc[dt].replace([np.inf, -np.inf], np.nan).dropna()
        if row.empty:
            continue
        strong = row[row > cfg.already_strong_cap]
        pool = strong if len(strong) else row[row > 0]
        if pool.empty:
            continue
        weights.at[dt, str(pool.idxmax())] = 1.0
    return weights


def leader_vs_bench_trail(
    member_closes: pd.DataFrame,
    bench_close: pd.Series,
    *,
    config: StructureGateConfig | None = None,
    leader_weights: pd.DataFrame | None = None,
) -> pd.Series:
    """Rolling sum of (prior-close leader daily ret − bench daily ret).

    Positive → stock_led; negative → index_lean / sticky lag.
    Uses prior day's leader decision (no same-bar lookahead).
    """
    cfg = config or StructureGateConfig()
    px = member_closes.astype(float).sort_index()
    bc = bench_close.astype(float).reindex(px.index).ffill()
    w = leader_weights if leader_weights is not None else strong_leader_weights(px, bc, config=cfg)
    w = w.reindex(px.index).fillna(0.0)
    bret = bc.pct_change().fillna(0.0)

    lret: list[float] = []
    for i, dt in enumerate(px.index):
        if i == 0:
            lret.append(0.0)
            continue
        prev = px.index[i - 1]
        row = w.loc[prev]
        active = row[row.abs() > 1e-12]
        if len(active) == 0:
            lret.append(0.0)
            continue
        sym = str(active.index[0])
        a = float(px.at[dt, sym])
        b = float(px.at[prev, sym])
        if not np.isfinite(a) or not np.isfinite(b) or b <= 0:
            lret.append(0.0)
        else:
            lret.append(a / b - 1.0)

    excess = pd.Series(lret, index=px.index) - bret
    return excess.rolling(cfg.leadership_trail_days, min_periods=10).sum()


def crowded_mask(
    features: pd.DataFrame,
    ers_excess: pd.Series,
    *,
    config: StructureGateConfig | None = None,
) -> pd.Series:
    cfg = config or StructureGateConfig()
    ex = ers_excess.reindex(features.index)
    return (
        ((features["top3_conc20"] >= cfg.top3_conc_min) & (features["overlap"] >= cfg.crowded_overlap_min))
        | (ex <= cfg.ers_lag_trigger)
        | (
            (features["strong_share"] >= cfg.strong_share_min)
            & (features["overlap"] >= cfg.strong_overlap_min)
        )
    ).fillna(False)


def sticky_regime(
    features: pd.DataFrame,
    lead_trail_long: pd.Series,
    *,
    config: StructureGateConfig | None = None,
) -> pd.Series:
    """Persistent sticky episode: enter on confirmed lag, stay until exit.

    ``harsh_ret`` ends sticky the same day (mode must not say sticky+cash).
    Trail catch-up / ``harsh_dd`` still use ``sticky_exit_confirm`` days.
    """
    cfg = config or StructureGateConfig()
    trail = lead_trail_long.reindex(features.index)
    above50 = features["above50"] > 0.5
    ret20 = features["ret20"]
    harsh_dd = (features["dd60"] <= -cfg.harsh_defense_dd).fillna(False)
    harsh_ret = (features["ret20"] <= cfg.harsh_defense_ret20).fillna(False)

    lag_enter = trail <= cfg.sticky_enter_trail
    breadth_enter = (trail <= cfg.sticky_breadth_trail) & (
        features["pct_beat60"] <= cfg.sticky_breadth_max
    )
    enter_raw = lag_enter | breadth_enter
    if cfg.sticky_require_above50:
        enter_raw = enter_raw & above50
    if cfg.sticky_require_ret20_pos:
        enter_raw = enter_raw & (ret20 > 0)
    # Do not arm sticky on a freefall day.
    enter_raw = enter_raw & ~harsh_ret

    exit_soft = (trail >= cfg.sticky_exit_trail) | harsh_dd
    if cfg.sticky_exit_on_below50:
        exit_soft = exit_soft | (~above50)

    active: list[bool] = []
    on = False
    enter_count = 0
    exit_count = 0
    for ent, soft, freefall in zip(
        enter_raw.fillna(False).tolist(),
        exit_soft.fillna(False).tolist(),
        harsh_ret.tolist(),
    ):
        if on:
            if freefall:
                on = False
                enter_count = 0
                exit_count = 0
                active.append(False)
                continue
            if soft:
                exit_count += 1
            else:
                exit_count = 0
            if exit_count >= cfg.sticky_exit_confirm:
                on = False
                enter_count = 0
                exit_count = 0
            active.append(on)
            continue

        if ent:
            enter_count += 1
        else:
            enter_count = 0
        if enter_count >= cfg.sticky_enter_confirm:
            on = True
            exit_count = 0
        active.append(on)

    return pd.Series(active, index=features.index, dtype=bool, name="sticky")


def thrust_mask(
    features: pd.DataFrame,
    *,
    config: StructureGateConfig | None = None,
) -> pd.Series:
    """Absolute bench melt-up / recovery thrust (orthogonal to sticky lag)."""
    cfg = config or StructureGateConfig()
    raw = (
        (features["ret5"] >= cfg.thrust_ret5_min)
        | (features["ret10"] >= cfg.thrust_ret10_min)
        | (features["bounce20"] >= cfg.thrust_bounce20_min)
        | (features["ret20"] >= cfg.thrust_ret20_min)
    )
    raw = raw & (features["ret20"] > cfg.harsh_defense_ret20)
    if cfg.thrust_require_above50:
        raw = raw & (features["above50"] > 0.5)

    confirm = max(1, int(cfg.thrust_confirm))
    if confirm <= 1:
        return raw.fillna(False).rename("thrust")

    on: list[bool] = []
    streak = 0
    for flag in raw.fillna(False).tolist():
        if flag:
            streak += 1
        else:
            streak = 0
        on.append(streak >= confirm)
    return pd.Series(on, index=features.index, dtype=bool, name="thrust")


def label_structure_modes(
    bench_close: pd.Series,
    member_closes: pd.DataFrame,
    *,
    config: StructureGateConfig | None = None,
) -> tuple[pd.Series, pd.DataFrame]:
    """Return daily mode series + feature frame (incl. helpers).

    Priority (highest wins):
      harsh_ret > thrust > sticky > harsh_dd > mild > index_lean
      > stock_led+crowded > stock_led/neutral ers > cash
    """
    cfg = config or StructureGateConfig()
    feat = structure_features(bench_close, member_closes, config=cfg)
    excess = trailing_ers_excess(bench_close, member_closes, config=cfg)
    strong_w = strong_leader_weights(member_closes, bench_close, config=cfg)
    lead_trail20 = leader_vs_bench_trail(
        member_closes, bench_close, config=cfg, leader_weights=strong_w
    )
    cfg_long = replace(cfg, leadership_trail_days=cfg.sticky_trail_days)
    lead_trail60 = leader_vs_bench_trail(
        member_closes, bench_close, config=cfg_long, leader_weights=strong_w
    )
    crowded = crowded_mask(feat, excess, config=cfg)
    sticky = sticky_regime(feat, lead_trail60, config=cfg)
    thrust = thrust_mask(feat, config=cfg)
    stock_led = lead_trail20 >= cfg.stock_led_min_trail
    index_lean = lead_trail20 <= cfg.index_lean_max_trail
    harsh_dd = (feat["dd60"] <= -cfg.harsh_defense_dd).fillna(False)
    harsh_ret = (feat["ret20"] <= cfg.harsh_defense_ret20).fillna(False)
    mild = (
        (feat["above50"] < 0.5)
        | (feat["dd60"] <= -cfg.mild_defense_dd)
        | (feat["ret20"] <= cfg.mild_defense_ret20)
    ).fillna(False)

    # Sticky/thrust lock bench through lagging dd60; only harsh_ret breaks them.
    sticky_lock = sticky & ~harsh_ret
    if cfg.thrust_force_bench:
        thrust_lock = thrust & ~harsh_ret
        if not cfg.thrust_overrides_dd_harsh:
            thrust_lock = thrust_lock & ~harsh_dd
    else:
        thrust_lock = pd.Series(False, index=feat.index)
    # Outside locks: stock sleeves need clear risk-on (not mild, not either harsh).
    risk_on = ~mild & ~harsh_dd & ~harsh_ret
    outside = ~(sticky_lock | thrust_lock) if cfg.sticky_forbid_stock_sleeves else (~thrust_lock)

    # Assign low → high so higher priority overwrites.
    mode = pd.Series("cash", index=feat.index, dtype=object)
    mode = mode.mask(outside & risk_on & ~index_lean, "ers")
    mode = mode.mask(outside & risk_on & stock_led & crowded, "strong")
    mode = mode.mask(outside & risk_on & index_lean, "bench")
    mode = mode.mask(outside & mild & ~harsh_ret, "cash")
    mode = mode.mask(outside & harsh_dd & ~harsh_ret, "cash")
    mode = mode.mask(sticky_lock, "bench")
    mode = mode.mask(thrust_lock, "bench")
    mode = mode.mask(harsh_ret, "cash")

    meta = feat.copy()
    meta["ers_excess60"] = excess
    meta["leader_vs_bench_trail"] = lead_trail20
    meta["leader_vs_bench_trail60"] = lead_trail60
    meta["sticky"] = sticky.astype(float)
    meta["thrust"] = thrust.astype(float)
    meta["stock_led"] = stock_led.astype(float)
    meta["index_lean"] = index_lean.astype(float)
    meta["bench_bias"] = (sticky_lock | thrust_lock | (index_lean & risk_on)).astype(float)
    meta["crowded"] = crowded.astype(float)
    meta["mild"] = mild.astype(float)
    meta["harsh_ret"] = harsh_ret.astype(float)
    meta["harsh_dd"] = harsh_dd.astype(float)
    meta["mode"] = mode
    return mode.rename("mode"), meta


@dataclass
class StructureSimResult:
    equity: pd.Series
    mode: pd.Series
    meta: pd.DataFrame
    trades: pd.DataFrame


def simulate_structure_gate(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    bench_open: pd.Series,
    bench_close: pd.Series,
    *,
    capital: float = 50_000.0,
    start: pd.Timestamp | None = None,
    fees: object | None = None,
    config: StructureGateConfig | None = None,
) -> StructureSimResult:
    """Next-open: cash / ers / strong leaders / bench ETF."""
    from qresearch.backtest.futu_costs import FutuUsEquityFees

    cfg = config or StructureGateConfig()
    fee_model = fees if fees is not None else FutuUsEquityFees(slippage_bps=3.0)
    mode, meta = label_structure_modes(bench_close, closes, config=cfg)
    book = EmergingRSWaveBook(gate="G1", config=cfg.ers_config or EmergingRSWaveConfig())
    ers_w, _ = book.generate_weights(closes, bench_close)
    strong_w = strong_leader_weights(closes, bench_close, config=cfg)

    px = closes.astype(float).sort_index()
    op = opens.astype(float).reindex(px.index)
    qo = bench_open.astype(float).reindex(px.index)
    qc = bench_close.astype(float).reindex(px.index)
    mode = mode.reindex(px.index).fillna("cash")
    ers_w = ers_w.reindex(px.index).fillna(0.0)
    strong_w = strong_w.reindex(px.index).fillna(0.0)

    dates = list(px.index)
    if start is None:
        start = dates[0]
    else:
        start = pd.Timestamp(start)

    cash = float(capital)
    pos_sym: str | None = None
    pos_shares = 0.0
    pos_kind = "cash"  # cash|ers|strong|bench
    pending = "cash"
    target_sym: str | None = None
    target_w = 0.0

    equity_rows: list[float] = []
    trades: list[dict] = []
    eq_index: list[pd.Timestamp] = []

    def _active(weights_row: pd.Series) -> tuple[str | None, float]:
        active = weights_row[weights_row.abs() > 1e-12]
        if len(active) == 0:
            return None, 0.0
        return str(active.index[0]), float(active.iloc[0])

    def _mark(dt: pd.Timestamp) -> float:
        if pos_kind == "cash" or pos_shares <= 0 or pos_sym is None:
            return cash
        if pos_kind == "bench":
            return cash + pos_shares * float(qc.at[dt])
        return cash + pos_shares * float(px.at[dt, pos_sym])

    def _sell_all(dt: pd.Timestamp, reason: str) -> None:
        nonlocal cash, pos_sym, pos_shares, pos_kind
        if pos_sym is None or pos_shares <= 0:
            return
        if pos_kind == "bench":
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

    def _buy_stock(dt: pd.Timestamp, sym: str, weight: float, reason: str, kind: str) -> None:
        nonlocal cash, pos_sym, pos_shares, pos_kind
        px_o = float(op.at[dt, sym])
        if not np.isfinite(px_o) or px_o <= 0:
            return
        shares = float(np.floor(cash * abs(weight) / px_o))
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
        pos_sym, pos_shares, pos_kind = sym, shares, kind
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

    def _buy_bench(dt: pd.Timestamp, reason: str) -> None:
        nonlocal cash, pos_sym, pos_shares, pos_kind
        px_o = float(qo.at[dt])
        if not np.isfinite(px_o) or px_o <= 0:
            return
        shares = float(np.floor(cash / px_o))
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
        pos_sym, pos_shares, pos_kind = "BENCH", shares, "bench"
        trades.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "side": "BUY",
                "symbol": "BENCH",
                "shares": round(shares, 4),
                "price": round(px_o, 4),
                "notional_usd": round(notional, 2),
                "cost_usd": round(cost, 2),
                "reason": reason,
            }
        )

    for dt in dates:
        if dt >= start:
            if pending == "cash":
                _sell_all(dt, "to_cash")
            elif pending == "bench":
                if pos_kind != "bench":
                    _sell_all(dt, "switch_to_bench")
                if pos_kind == "cash":
                    _buy_bench(dt, "bench")
            elif pending in ("ers", "strong"):
                kind = pending
                enter_reason = f"{kind}_enter"
                rotate_reason = f"{kind}_rotate"
                flat_reason = f"{kind}_flat"
                if pos_kind not in ("cash", kind):
                    _sell_all(dt, f"switch_to_{kind}")
                sym, w = target_sym, target_w
                if sym is None or w <= 0:
                    if pos_kind == kind:
                        _sell_all(dt, flat_reason)
                else:
                    if pos_kind == kind and pos_sym != sym:
                        _sell_all(dt, rotate_reason)
                    if pos_kind == "cash":
                        _buy_stock(dt, sym, w, enter_reason, kind)

            eq_index.append(dt)
            equity_rows.append(_mark(dt))

        m = str(mode.at[dt])
        if m == "cash":
            pending, target_sym, target_w = "cash", None, 0.0
        elif m == "bench":
            pending, target_sym, target_w = "bench", "BENCH", 1.0
        elif m == "strong":
            sym, w = _active(strong_w.loc[dt])
            pending, target_sym, target_w = "strong", sym, w
        else:
            sym, w = _active(ers_w.loc[dt])
            pending, target_sym, target_w = "ers", sym, w

        if dt < start:
            cash = float(capital)
            pos_sym, pos_shares, pos_kind = None, 0.0, "cash"

    idx = pd.DatetimeIndex(eq_index)
    return StructureSimResult(
        equity=pd.Series(equity_rows, index=idx, name="equity"),
        mode=mode.reindex(idx),
        meta=meta.reindex(idx),
        trades=pd.DataFrame(trades),
    )


# Back-compat aliases (deprecated names)
sticky_index_strong_regime = sticky_regime
index_thrust_mask = thrust_mask
crowded_structure_mask = crowded_mask
