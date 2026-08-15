"""Universe-agnostic Structure Gate: modes cash / ers / strong / bench.

Canonical names (code = docs):
- Modes: cash | ers | strong | bench
- Locus: stock_led | index_lean | neutral
- Sleeves: sticky | thrust | crowded
- Defense: mild | harsh_dd | harsh_ret | mild_top

Priority (highest wins):
  harsh_ret > thrust > sticky > harsh_dd > reentry > mild > index_lean
  > stock_led+crowded > ers > cash

Defaults = v8. Use ``StructureGateConfig.v9()`` for hysteresis / mild-top /
split-slippage variant. ``v10()`` is the cross-book preset (SPY regime +
union stock sleeve + best-of ETF bench) used with ``simulate_structure_gate_cross``.
``v11()`` / ``v13()`` share the SPY/QQQ/SMH blend capital split; v13 adds
mode hysteresis + risk-override cooldown pierce (see ``stabilize_modes_v13``).
``v14()`` keeps v13 locks but enters stock immediately when unlocked and
enforces a minimum hold before soft exit.
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
    """Defaults = v8 universal tune (50-trial in-window best soft coverage)."""

    top_k_conc: int = 3
    top3_conc_min: float = 0.35
    crowded_overlap_min: float = 0.45
    strong_share_min: float = 0.35
    strong_overlap_min: float = 0.45
    ers_lag_lookback: int = 60
    ers_lag_trigger: float = -0.08
    # Already-strong leadership for strong mode
    already_strong_cap: float = 0.10
    strong_lookback: int = 60
    # Short trail (tactical stock_led / index_lean)
    leadership_trail_days: int = 20
    stock_led_min_trail: float = 0.025
    index_lean_max_trail: float = -0.025
    # Sticky sleeve
    sticky_trail_days: int = 60
    sticky_enter_trail: float = -0.06
    sticky_enter_confirm: int = 2
    sticky_exit_trail: float = -0.02
    sticky_exit_confirm: int = 6
    sticky_require_above50: bool = True
    sticky_require_ret20_pos: bool = False
    sticky_breadth_max: float = 0.50
    sticky_breadth_trail: float = -0.12
    sticky_exit_on_below50: bool = False
    sticky_forbid_stock_sleeves: bool = True
    # Thrust sleeve
    thrust_ret5_min: float = 0.04
    thrust_ret10_min: float = 0.07
    thrust_bounce20_min: float = 0.06
    thrust_ret20_min: float = 0.08
    thrust_require_above50: bool = True
    thrust_confirm: int = 1
    thrust_overrides_dd_harsh: bool = True
    thrust_force_bench: bool = True
    # Mild / harsh defense
    mild_defense_dd: float = 0.06
    mild_defense_ret20: float = -0.04
    harsh_defense_dd: float = 0.18
    harsh_defense_ret20: float = -0.12
    # SMA50 hysteresis band (fraction). 0 = raw close vs SMA50 (v8).
    sma50_hysteresis: float = 0.0
    # Vol-adaptive mild: widen dd/ret20 thresholds with realized bench vol.
    # Off by default (v8). When on: thr = max(fixed, k * σ * √horizon).
    mild_vol_adaptive: bool = False
    mild_vol_lookback: int = 60
    mild_vol_dd_k: float = 2.5
    mild_vol_ret20_k: float = 2.0
    # Mild-top: high-level distribution / breadth divergence demotes sticky/thrust
    # so Mild can flatten instead of riding ETF down. Off by default (v8).
    mild_top_enabled: bool = False
    mild_top_breadth_max: float = 0.30
    mild_top_breadth_confirm: int = 3
    mild_top_down_vol_k: float = 1.0
    mild_top_down_confirm: int = 3
    mild_top_volume_ratio: float = 1.5
    # Fast re-entry after mild dips (V-recovery). Forces bench even below SMA50.
    # Off by default (v8). Priority: between harsh_dd and mild.
    reentry_force_bench: bool = False
    reentry_ret5_min: float = 0.03
    reentry_ret10_min: float = 0.05
    reentry_bounce20_min: float = 0.05
    # Split slippage (research). Used by simulate when fee model supports replace.
    bench_slippage_bps: float = 3.0
    stock_slippage_bps: float = 3.0
    # Book-level peak equity hard stop (None = disabled).
    # When equity / peak - 1 <= -book_peak_dd_stop → flatten & halt
    # until non-cash signal confirms for book_dd_reentry_confirm days.
    book_peak_dd_stop: float | None = None
    book_dd_reentry_confirm: int = 3
    ers_config: EmergingRSWaveConfig | None = None
    # --- v13: mode hysteresis + risk-override pierce ---
    # Prefer price/RS hysteresis over pure time cooldown for soft switches
    # (ers/strong ↔ bench). Enter needs trail >= mode_enter_trail; exit needs
    # trail <= mode_exit_trail. Soft switches also respect cooldown_days, but
    # harsh_defense / held-stock crash pierce immediately to cash.
    mode_hysteresis_enabled: bool = False
    mode_enter_trail: float = 0.025
    mode_exit_trail: float = -0.01
    mode_switch_cooldown_days: int = 2
    risk_override_enabled: bool = False
    risk_override_stock_1d: float = 0.08
    # --- v14: immediate enter when unlocked + minimum stock-mode hold ---
    # When True, bench/cash → ers/strong ignores mode_enter_trail (locks still apply).
    mode_enter_immediate: bool = False
    # Soft exits from ers/strong blocked until this many days in stock mode
    # (risk cash still pierces). 0 = disabled (v13 behavior).
    mode_min_hold_days: int = 0

    @classmethod
    def v8(cls) -> "StructureGateConfig":
        """Canonical v8 defaults (same as ``StructureGateConfig()``)."""
        return cls()

    @classmethod
    def v9(cls) -> "StructureGateConfig":
        """v9: sticky/SMA hysteresis, mild-top demote, split ETF/stock slip."""
        return cls(
            sticky_enter_trail=-0.065,
            sticky_exit_trail=-0.045,
            sticky_enter_confirm=2,
            sticky_exit_confirm=6,
            sma50_hysteresis=0.005,
            mild_top_enabled=True,
            mild_top_breadth_max=0.30,
            mild_top_breadth_confirm=3,
            mild_top_down_vol_k=1.0,
            mild_top_down_confirm=3,
            mild_top_volume_ratio=1.5,
            bench_slippage_bps=3.0,
            stock_slippage_bps=8.0,
        )

    @classmethod
    def v10(cls) -> "StructureGateConfig":
        """v10 cross-book: same defense/sleeve knobs as v8.

        Cross behaviour lives in ``simulate_structure_gate_cross``:
        SPY regimes the day; ERS/strong pick from a union universe; bench
        rotates to the strongest of {SPY, QQQ, SMH} on a 20d return score.
        """
        return cls()

    @classmethod
    def v11(cls) -> "StructureGateConfig":
        """v11 blended sleeves: same knobs as v8.

        Capital is split across independent books (default SPY 40% / QQQ 30% /
        SMH 30%); each runs ``simulate_structure_gate`` on its own universe and
        the equities are summed. See ``blend_structure_gate_books``.
        """
        return cls()

    @classmethod
    def v13(cls) -> "StructureGateConfig":
        """v13 blend: v8/v11 base + mode hysteresis + risk-override pierce.

        Soft mode switches (ers/strong ↔ bench) use asymmetric trail hysteresis
        and a short cooldown. ``harsh_defense`` or a held-stock 1d crash pierces
        stickiness and allows immediate cash.

        Knobs below = best of 36-trial random tune on windows
        2023-01-01→2024-01-01 and 2025-08-07→2026-08-07
        (see ``examples/run_structure_gate_v13_vs_v11.py``).
        """
        return cls(
            mode_hysteresis_enabled=True,
            mode_enter_trail=0.035,
            mode_exit_trail=-0.015,
            mode_switch_cooldown_days=3,
            risk_override_enabled=True,
            risk_override_stock_1d=0.08,
            mild_defense_dd=0.06,
            mild_defense_ret20=-0.05,
            harsh_defense_dd=0.20,
            harsh_defense_ret20=-0.12,
            stock_led_min_trail=0.03,
            index_lean_max_trail=-0.03,
            sma50_hysteresis=0.0,
            mode_enter_immediate=False,
            mode_min_hold_days=0,
        )

    @classmethod
    def v14(cls) -> "StructureGateConfig":
        """v14: same locks/defense as v13; enter stock immediately when unlocked.

        Differences vs v13:
        - ``mode_enter_immediate=True`` — no +trail gate to enter ers/strong
        - ``mode_min_hold_days=3`` — soft exit blocked for 3 sessions after entry
        - ``mode_switch_cooldown_days=0`` — min-hold replaces soft cooldown
        Sticky/thrust/reentry/harsh locks unchanged. Risk cash still pierces hold.
        """
        return cls(
            mode_hysteresis_enabled=True,
            mode_enter_trail=0.035,  # unused while mode_enter_immediate
            mode_exit_trail=-0.015,
            mode_switch_cooldown_days=0,
            mode_enter_immediate=True,
            mode_min_hold_days=3,
            risk_override_enabled=True,
            risk_override_stock_1d=0.08,
            mild_defense_dd=0.06,
            mild_defense_ret20=-0.05,
            harsh_defense_dd=0.20,
            harsh_defense_ret20=-0.12,
            stock_led_min_trail=0.03,
            index_lean_max_trail=-0.03,
            sma50_hysteresis=0.0,
        )


# Default capital weights (must sum to 1.0).
V11_BOOK_WEIGHTS: dict[str, float] = {"SPY": 0.40, "QQQ": 0.30, "SMH": 0.30}
# Production / paper default for v13: two-sleeve SPY/QQQ (no SMH).
V13_BOOK_WEIGHTS: dict[str, float] = {"SPY": 0.50, "QQQ": 0.50}
V14_BOOK_WEIGHTS: dict[str, float] = dict(V13_BOOK_WEIGHTS)


def blend_structure_gate_books(
    book_results: dict[str, "StructureSimResult"],
    weights: dict[str, float] | None = None,
    *,
    capital: float = 50_000.0,
) -> tuple[pd.Series, pd.DataFrame]:
    """Sum independent book equities into one portfolio path.

    ``book_results`` maps book name → ``StructureSimResult`` already simulated
    with ``capital * weight[book]``. Returns (blended_equity, weight_frame).
    """
    w = dict(weights or V11_BOOK_WEIGHTS)
    s = float(sum(w.values()))
    if s <= 0:
        raise ValueError("weights must sum to a positive number")
    w = {k: float(v) / s for k, v in w.items()}

    eqs: dict[str, pd.Series] = {}
    for book, weight in w.items():
        if book not in book_results:
            raise KeyError(f"missing book result for {book}")
        eqs[book] = book_results[book].equity.astype(float)
    panel = pd.DataFrame(eqs).sort_index().ffill()
    # Books may start on slightly different calendars; before first value use
    # that sleeve's starting capital so the sum stays near ``capital``.
    for book, weight in w.items():
        start_cap = float(capital) * weight
        panel[book] = panel[book].fillna(start_cap)
    blended = panel.sum(axis=1).rename("equity")
    return blended, panel


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


def mild_thresholds(
    features: pd.DataFrame,
    bench_close: pd.Series,
    *,
    config: StructureGateConfig | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Return per-day (dd_thr ≤ 0, ret20_thr ≤ 0) for mild defense."""
    cfg = config or StructureGateConfig()
    idx = features.index
    dd_thr = pd.Series(-abs(cfg.mild_defense_dd), index=idx, dtype=float)
    ret_thr = pd.Series(float(cfg.mild_defense_ret20), index=idx, dtype=float)
    if not cfg.mild_vol_adaptive:
        return dd_thr, ret_thr

    bc = bench_close.astype(float).reindex(idx).ffill()
    lb = max(10, int(cfg.mild_vol_lookback))
    sig = bc.pct_change().rolling(lb, min_periods=max(5, lb // 3)).std().clip(lower=1e-4)
    dd_vol = cfg.mild_vol_dd_k * sig * np.sqrt(60.0)
    ret_vol = cfg.mild_vol_ret20_k * sig * np.sqrt(20.0)
    dd_thr = -pd.concat(
        [pd.Series(abs(cfg.mild_defense_dd), index=idx), dd_vol], axis=1
    ).max(axis=1)
    ret_thr = -pd.concat(
        [pd.Series(abs(cfg.mild_defense_ret20), index=idx), ret_vol], axis=1
    ).max(axis=1)
    return dd_thr, ret_thr


def reentry_mask(
    features: pd.DataFrame,
    *,
    config: StructureGateConfig | None = None,
) -> pd.Series:
    """V-recovery re-entry: bounce/short thrust without requiring above50."""
    cfg = config or StructureGateConfig()
    if not cfg.reentry_force_bench:
        return pd.Series(False, index=features.index, dtype=bool, name="reentry")
    raw = (
        (features["ret5"] >= cfg.reentry_ret5_min)
        | (features["ret10"] >= cfg.reentry_ret10_min)
        | (features["bounce20"] >= cfg.reentry_bounce20_min)
    )
    raw = raw & (features["ret20"] > cfg.harsh_defense_ret20)
    return raw.fillna(False).rename("reentry")


def above50_hysteresis(
    bench_close: pd.Series,
    *,
    hysteresis: float = 0.0,
    window: int = 50,
) -> pd.Series:
    """SMA50 membership with optional band to avoid boundary flip-flops.

    hysterisis=0 → close > SMA50. Otherwise: drop below SMA*(1-h) to leave
    above-zone; reclaim SMA*(1+h) to re-enter.
    """
    bc = bench_close.astype(float)
    sma = bc.rolling(window, min_periods=max(20, window // 2)).mean()
    h = max(0.0, float(hysteresis))
    if h <= 0:
        return (bc > sma).fillna(False).rename("above50")

    enter_above = bc > sma * (1.0 + h)
    leave_above = bc < sma * (1.0 - h)
    on: list[bool] = []
    above = False
    for ent, leave, valid in zip(
        enter_above.fillna(False).tolist(),
        leave_above.fillna(False).tolist(),
        sma.notna().tolist(),
    ):
        if not valid:
            on.append(False)
            continue
        if above:
            if leave:
                above = False
        else:
            if ent:
                above = True
        on.append(above)
    return pd.Series(on, index=bc.index, dtype=bool, name="above50")


def _confirm_streak(raw: pd.Series, need: int) -> pd.Series:
    need = max(1, int(need))
    out: list[bool] = []
    streak = 0
    for flag in raw.fillna(False).tolist():
        if flag:
            streak += 1
        else:
            streak = 0
        out.append(streak >= need)
    return pd.Series(out, index=raw.index, dtype=bool)


def mild_topping_mask(
    features: pd.DataFrame,
    bench_close: pd.Series,
    *,
    bench_volume: pd.Series | None = None,
    config: StructureGateConfig | None = None,
) -> pd.Series:
    """High-level distribution / breadth divergence (mild-top).

    Triggers when breadth stays weak while still above SMA50, or when
    consecutive large down days (optionally on above-average volume) print
    without yet hitting harsh_ret.
    """
    cfg = config or StructureGateConfig()
    idx = features.index
    if not cfg.mild_top_enabled:
        return pd.Series(False, index=idx, dtype=bool, name="mild_top")

    above50 = features["above50"] > 0.5
    breadth_raw = (features["breadth"] <= cfg.mild_top_breadth_max) & above50
    breadth_hit = _confirm_streak(breadth_raw, cfg.mild_top_breadth_confirm)

    bc = bench_close.astype(float).reindex(idx).ffill()
    bret = bc.pct_change()
    vol = bret.rolling(20, min_periods=5).std().clip(lower=1e-4)
    heavy_down = (bret <= -cfg.mild_top_down_vol_k * vol).fillna(False)
    if bench_volume is not None:
        volu = bench_volume.astype(float).reindex(idx)
        avg = volu.rolling(20, min_periods=5).mean()
        climax = (volu >= cfg.mild_top_volume_ratio * avg).fillna(False)
        heavy_down = heavy_down & climax
    down_hit = _confirm_streak(heavy_down, cfg.mild_top_down_confirm)

    # Still not a freefall (harsh_ret owns that).
    not_freefall = features["ret20"] > cfg.harsh_defense_ret20
    return ((breadth_hit | down_hit) & not_freefall.fillna(False)).rename("mild_top")


def stabilize_modes_v13(
    raw_mode: pd.Series,
    lead_trail: pd.Series,
    harsh_ret: pd.Series,
    harsh_dd: pd.Series,
    *,
    config: StructureGateConfig | None = None,
) -> tuple[pd.Series, pd.DataFrame]:
    """Stick soft mode flips via hysteresis (+ optional cooldown / min-hold).

    - Enter stock sleeves (bench/cash → ers/strong) only if
      ``lead_trail >= mode_enter_trail`` (default +2.5%), unless
      ``mode_enter_immediate`` (v14) — then enter as soon as unlocked.
    - Exit stock → bench only if ``lead_trail <= mode_exit_trail`` (default −1%),
      and only after ``mode_min_hold_days`` in ers/strong (v14).
    - Soft switches also respect ``mode_switch_cooldown_days``.
    - Risk override: ``harsh_ret`` / ``harsh_dd`` always allow immediate cash
      (cooldown + hysteresis + min-hold pierced for liquidation).
    - Mild (non-harsh) cash is still allowed immediately (defensive).
    """
    cfg = config or StructureGateConfig()
    idx = raw_mode.index
    trail = lead_trail.reindex(idx).astype(float)
    h_ret = harsh_ret.reindex(idx).fillna(False).astype(bool)
    h_dd = harsh_dd.reindex(idx).fillna(False).astype(bool)
    use_hyst = bool(cfg.mode_hysteresis_enabled)
    cooldown = max(0, int(cfg.mode_switch_cooldown_days))
    enter_thr = float(cfg.mode_enter_trail)
    exit_thr = float(cfg.mode_exit_trail)
    enter_imm = bool(cfg.mode_enter_immediate)
    min_hold = max(0, int(cfg.mode_min_hold_days))

    out: list[str] = []
    blocked: list[float] = []
    risk_pierce: list[float] = []
    cur: str | None = None
    days_since = 10**9
    days_in_stock = 0

    for i in range(len(idx)):
        desired = str(raw_mode.iat[i])
        t = trail.iat[i]
        t_ok = bool(np.isfinite(t))
        t_val = float(t) if t_ok else 0.0
        risk = bool(h_ret.iat[i] or h_dd.iat[i])

        if cur is None:
            cur = desired
            out.append(cur)
            blocked.append(0.0)
            risk_pierce.append(0.0)
            # Seeded mode does not start a cooldown clock.
            days_since = 10**9
            days_in_stock = 1 if cur in ("ers", "strong") else 0
            continue

        allow = True
        pierce = 0.0

        # Risk override: always allow forced cash.
        if risk and desired == "cash":
            allow = True
            pierce = 1.0 if cur != "cash" else 0.0
        elif desired == "cash":
            # Mild / other defensive cash — allow (do not trap in stocks).
            allow = True
        else:
            stock_cur = cur in ("ers", "strong")
            stock_des = desired in ("ers", "strong")
            if use_hyst and t_ok:
                if (cur in ("bench", "cash")) and stock_des:
                    allow = True if enter_imm else (t_val >= enter_thr)
                elif stock_cur and desired == "bench":
                    if min_hold > 0 and days_in_stock < min_hold:
                        allow = False
                    else:
                        allow = t_val <= exit_thr
                elif stock_cur and stock_des and cur != desired:
                    # ers ↔ strong: require clear leadership, not noise;
                    # also respect min-hold (treat as soft switch).
                    if min_hold > 0 and days_in_stock < min_hold:
                        allow = False
                    elif enter_imm:
                        allow = True
                    else:
                        allow = t_val >= enter_thr
                elif cur == "cash" and desired == "bench":
                    allow = True
            elif use_hyst and not t_ok:
                # No trail: still honor min-hold / immediate enter.
                if (cur in ("bench", "cash")) and stock_des:
                    allow = True if enter_imm else False
                elif stock_cur and desired == "bench":
                    allow = not (min_hold > 0 and days_in_stock < min_hold)
                elif stock_cur and stock_des and cur != desired:
                    if min_hold > 0 and days_in_stock < min_hold:
                        allow = False
                    else:
                        allow = bool(enter_imm)
            # Soft-switch cooldown (secondary). Risk already handled above.
            if allow and cooldown > 0 and desired != cur:
                soft = (cur in ("ers", "strong", "bench")) and (
                    desired in ("ers", "strong", "bench")
                )
                if soft and days_since < cooldown:
                    allow = False

        if allow and desired != cur:
            cur = desired
            days_since = 0
            blocked.append(0.0)
            days_in_stock = 1 if cur in ("ers", "strong") else 0
        else:
            if desired != cur:
                blocked.append(1.0)
            else:
                blocked.append(0.0)
            days_since += 1
            if cur in ("ers", "strong"):
                days_in_stock += 1
            else:
                days_in_stock = 0
        risk_pierce.append(pierce)
        out.append(cur)

    mode = pd.Series(out, index=idx, dtype=object, name="mode")
    audit = pd.DataFrame(
        {
            "mode_raw": raw_mode.reindex(idx).astype(object),
            "mode_switch_blocked": blocked,
            "risk_override_pierce": risk_pierce,
        },
        index=idx,
    )
    return mode, audit


def label_structure_modes(
    bench_close: pd.Series,
    member_closes: pd.DataFrame,
    *,
    config: StructureGateConfig | None = None,
    bench_volume: pd.Series | None = None,
) -> tuple[pd.Series, pd.DataFrame]:
    """Return daily mode series + feature frame (incl. helpers).

    Priority (highest wins):
      harsh_ret > thrust > sticky > harsh_dd > reentry > mild > index_lean
      > stock_led+crowded > stock_led/neutral ers > cash

    When ``mild_top`` is on and Mild is active, sticky/thrust lose their
    ability to override Mild (demote lock → allow cash).

    When v13 hysteresis / risk-override flags are on, soft mode flips are
    stabilized via ``stabilize_modes_v13`` after the raw priority assignment.
    """
    cfg = config or StructureGateConfig()
    feat = structure_features(bench_close, member_closes, config=cfg)
    # Replace raw above50 with hysteretic band when configured (v9).
    if cfg.sma50_hysteresis and cfg.sma50_hysteresis > 0:
        feat = feat.copy()
        feat["above50"] = above50_hysteresis(
            bench_close, hysteresis=cfg.sma50_hysteresis
        ).astype(float)
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
    reentry = reentry_mask(feat, config=cfg)
    mild_top = mild_topping_mask(
        feat, bench_close, bench_volume=bench_volume, config=cfg
    )
    stock_led = lead_trail20 >= cfg.stock_led_min_trail
    index_lean = lead_trail20 <= cfg.index_lean_max_trail
    harsh_dd = (feat["dd60"] <= -cfg.harsh_defense_dd).fillna(False)
    harsh_ret = (feat["ret20"] <= cfg.harsh_defense_ret20).fillna(False)
    dd_thr, ret_thr = mild_thresholds(feat, bench_close, config=cfg)
    mild = (
        (feat["above50"] < 0.5)
        | (feat["dd60"] <= dd_thr)
        | (feat["ret20"] <= ret_thr)
    ).fillna(False)

    # Sticky/thrust/reentry lock bench through lagging dd60; only harsh_ret breaks them.
    # mild_top + mild → demote locks so Mild cash can fire (avoid riding ETF down).
    demote = mild_top & mild
    sticky_lock = sticky & ~harsh_ret & ~demote
    if cfg.thrust_force_bench:
        thrust_lock = thrust & ~harsh_ret & ~demote
        if not cfg.thrust_overrides_dd_harsh:
            thrust_lock = thrust_lock & ~harsh_dd
    else:
        thrust_lock = pd.Series(False, index=feat.index)
    reentry_lock = reentry & ~harsh_ret & ~harsh_dd & ~demote
    # Outside locks: stock sleeves need clear risk-on (not mild, not either harsh).
    risk_on = ~mild & ~harsh_dd & ~harsh_ret
    locked = sticky_lock | thrust_lock | reentry_lock
    outside = ~locked if cfg.sticky_forbid_stock_sleeves else ~(thrust_lock | reentry_lock)

    # Assign low → high so higher priority overwrites.
    mode = pd.Series("cash", index=feat.index, dtype=object)
    mode = mode.mask(outside & risk_on & ~index_lean, "ers")
    mode = mode.mask(outside & risk_on & stock_led & crowded, "strong")
    mode = mode.mask(outside & risk_on & index_lean, "bench")
    mode = mode.mask(outside & mild & ~harsh_ret, "cash")
    mode = mode.mask(outside & harsh_dd & ~harsh_ret, "cash")
    mode = mode.mask(reentry_lock, "bench")
    mode = mode.mask(sticky_lock, "bench")
    mode = mode.mask(thrust_lock, "bench")
    mode = mode.mask(harsh_ret, "cash")

    meta = feat.copy()
    meta["ers_excess60"] = excess
    meta["leader_vs_bench_trail"] = lead_trail20
    meta["leader_vs_bench_trail60"] = lead_trail60
    # sticky/thrust columns = effective locks (post demote) so audits never
    # show sticky-ON + cash from mild-top override.
    meta["sticky_raw"] = sticky.astype(float)
    meta["thrust_raw"] = thrust.astype(float)
    meta["sticky"] = sticky_lock.astype(float)
    meta["thrust"] = thrust_lock.astype(float)
    meta["reentry"] = reentry.astype(float)
    meta["mild_top"] = mild_top.astype(float)
    meta["lock_demote"] = demote.astype(float)
    meta["mild_dd_thr"] = dd_thr
    meta["mild_ret20_thr"] = ret_thr
    meta["stock_led"] = stock_led.astype(float)
    meta["index_lean"] = index_lean.astype(float)
    meta["bench_bias"] = (locked | (index_lean & risk_on)).astype(float)
    meta["crowded"] = crowded.astype(float)
    meta["mild"] = mild.astype(float)
    meta["harsh_ret"] = harsh_ret.astype(float)
    meta["harsh_dd"] = harsh_dd.astype(float)
    meta["mode_raw"] = mode.astype(object)
    if cfg.mode_hysteresis_enabled or cfg.risk_override_enabled:
        mode, audit = stabilize_modes_v13(
            mode, lead_trail20, harsh_ret, harsh_dd, config=cfg
        )
        meta["mode_switch_blocked"] = audit["mode_switch_blocked"]
        meta["risk_override_pierce"] = audit["risk_override_pierce"]
    meta["mode"] = mode
    return mode.rename("mode"), meta


@dataclass
class StructureSimResult:
    equity: pd.Series
    mode: pd.Series
    meta: pd.DataFrame
    trades: pd.DataFrame


def _split_fee_models(fees: object, cfg: StructureGateConfig) -> tuple[object, object]:
    """Return (bench_fees, stock_fees) honoring v9 split slippage when possible."""
    from qresearch.backtest.futu_costs import FutuUsEquityFees

    if isinstance(fees, FutuUsEquityFees):
        return (
            fees.with_slippage(cfg.bench_slippage_bps),
            fees.with_slippage(cfg.stock_slippage_bps),
        )
    return fees, fees


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
    bench_volume: pd.Series | None = None,
) -> StructureSimResult:
    """Next-open: cash / ers / strong leaders / bench ETF."""
    from qresearch.backtest.futu_costs import FutuUsEquityFees

    cfg = config or StructureGateConfig()
    fee_model = fees if fees is not None else FutuUsEquityFees(slippage_bps=3.0)
    bench_fees, stock_fees = _split_fee_models(fee_model, cfg)
    mode, meta = label_structure_modes(
        bench_close, closes, config=cfg, bench_volume=bench_volume
    )
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
    peak_eq = float(capital)
    dd_halt = False
    dd_reentry = 0
    dd_stop = (
        abs(float(cfg.book_peak_dd_stop))
        if cfg.book_peak_dd_stop is not None and cfg.book_peak_dd_stop > 0
        else None
    )
    reentry_need = max(1, int(cfg.book_dd_reentry_confirm))
    mode_exec = mode.copy()
    halt_flags: list[float] = []
    crash_flags: list[float] = []

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

    def _fees_for_kind(kind: str) -> object:
        return bench_fees if kind == "bench" else stock_fees

    def _sell_all(dt: pd.Timestamp, reason: str) -> None:
        nonlocal cash, pos_sym, pos_shares, pos_kind
        if pos_sym is None or pos_shares <= 0:
            return
        kind = pos_kind
        if kind == "bench":
            px_o = float(qo.at[dt])
        else:
            px_o = float(op.at[dt, pos_sym])
        if not np.isfinite(px_o) or px_o <= 0:
            return
        notional = pos_shares * px_o
        cost = float(_fees_for_kind(kind).total_cost_usd(notional, px_o))
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
        cost = float(stock_fees.total_cost_usd(notional, px_o))
        if notional + cost > cash:
            shares = float(np.floor((cash * 0.999) / px_o))
            if shares < 1:
                return
            notional = shares * px_o
            cost = float(stock_fees.total_cost_usd(notional, px_o))
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
        cost = float(bench_fees.total_cost_usd(notional, px_o))
        if notional + cost > cash:
            shares = float(np.floor((cash * 0.999) / px_o))
            if shares < 1:
                return
            notional = shares * px_o
            cost = float(bench_fees.total_cost_usd(notional, px_o))
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
                reason = "to_cash"
                if dd_halt:
                    reason = "book_dd_stop"
                elif crash_flags and crash_flags[-1] >= 1.0:
                    # previous close marked crash → this open flattens
                    reason = "risk_override_stock"
                _sell_all(dt, reason)
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
            marked = _mark(dt)
            equity_rows.append(marked)
            if marked > peak_eq:
                peak_eq = marked
            if dd_stop is not None and peak_eq > 0:
                dd_now = marked / peak_eq - 1.0
                if dd_now <= -dd_stop:
                    dd_halt = True
                    dd_reentry = 0

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

        # v13 risk override: held-stock 1d crash pierces soft stickiness → cash.
        stock_crash = False
        if (
            cfg.risk_override_enabled
            and pos_kind in ("ers", "strong")
            and pos_sym is not None
            and pos_sym in px.columns
        ):
            loc = px.index.get_loc(dt)
            if isinstance(loc, int) and loc > 0:
                prev = float(px.iloc[loc - 1][pos_sym])
                now = float(px.iloc[loc][pos_sym])
                if np.isfinite(prev) and prev > 0 and np.isfinite(now):
                    if now / prev - 1.0 <= -abs(float(cfg.risk_override_stock_1d)):
                        stock_crash = True
                        pending, target_sym, target_w = "cash", None, 0.0
                        mode_exec.at[dt] = "cash"
        crash_flags.append(1.0 if stock_crash else 0.0)

        # Book DD hard stop: flatten and stay cash until non-cash signal confirms.
        if dd_halt:
            if m != "cash":
                dd_reentry += 1
            else:
                dd_reentry = 0
            if dd_reentry >= reentry_need:
                dd_halt = False
                dd_reentry = 0
                # keep pending from signal above
            else:
                pending, target_sym, target_w = "cash", None, 0.0
                mode_exec.at[dt] = "cash"
        halt_flags.append(1.0 if dd_halt else 0.0)

        if dt < start:
            cash = float(capital)
            pos_sym, pos_shares, pos_kind = None, 0.0, "cash"
            peak_eq = float(capital)
            dd_halt = False
            dd_reentry = 0

    idx = pd.DatetimeIndex(eq_index)
    meta = meta.copy()
    meta["book_dd_halt"] = pd.Series(halt_flags, index=mode.index, dtype=float).reindex(meta.index)
    meta["stock_crash_override"] = pd.Series(
        crash_flags, index=mode.index, dtype=float
    ).reindex(meta.index)
    meta["mode_signal"] = mode
    meta["mode"] = mode_exec
    return StructureSimResult(
        equity=pd.Series(equity_rows, index=idx, name="equity"),
        mode=mode_exec.reindex(idx),
        meta=meta.reindex(idx),
        trades=pd.DataFrame(trades),
    )


def best_etf_by_momentum(
    etf_closes: pd.DataFrame,
    *,
    lookback: int = 20,
    default: str | None = None,
) -> pd.Series:
    """Daily ticker with highest ``lookback``-day total return among ETF columns."""
    px = etf_closes.astype(float).sort_index()
    ret = px / px.shift(lookback) - 1.0
    fallback = default or (str(px.columns[0]) if len(px.columns) else "")
    picks: list[str] = []
    for dt in ret.index:
        row = ret.loc[dt].replace([np.inf, -np.inf], np.nan).dropna()
        if row.empty:
            picks.append(fallback)
        else:
            picks.append(str(row.idxmax()))
    return pd.Series(picks, index=ret.index, name="best_etf")


def simulate_structure_gate_cross(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    etf_opens: pd.DataFrame,
    etf_closes: pd.DataFrame,
    *,
    regime_etf: str = "SPY",
    capital: float = 50_000.0,
    start: pd.Timestamp | None = None,
    fees: object | None = None,
    config: StructureGateConfig | None = None,
    etf_momentum_lookback: int = 20,
) -> StructureSimResult:
    """Cross-book Structure Gate (v10).

    - Regime / defense / sticky / thrust: measured on ``regime_etf`` (default SPY).
    - ``ers`` / ``strong``: pick from the union stock panel vs regime close.
    - ``bench``: next-open full weight in the ETF with best ``etf_momentum_lookback``
      return among ``etf_closes`` columns (typically SPY/QQQ/SMH).
    """
    from qresearch.backtest.futu_costs import FutuUsEquityFees

    cfg = config or StructureGateConfig.v10()
    fee_model = fees if fees is not None else FutuUsEquityFees(slippage_bps=3.0)
    bench_fees, stock_fees = _split_fee_models(fee_model, cfg)

    if regime_etf not in etf_closes.columns:
        raise ValueError(f"regime_etf={regime_etf} missing from etf_closes")

    regime_close = etf_closes[regime_etf].astype(float)
    regime_vol = None
    mode, meta = label_structure_modes(regime_close, closes, config=cfg, bench_volume=regime_vol)
    book = EmergingRSWaveBook(gate="G1", config=cfg.ers_config or EmergingRSWaveConfig())
    ers_w, _ = book.generate_weights(closes, regime_close)
    strong_w = strong_leader_weights(closes, regime_close, config=cfg)
    best_etf = best_etf_by_momentum(
        etf_closes, lookback=etf_momentum_lookback, default=regime_etf
    )

    px = closes.astype(float).sort_index()
    op = opens.astype(float).reindex(px.index)
    eo = etf_opens.astype(float).reindex(px.index)
    ec = etf_closes.astype(float).reindex(px.index)
    mode = mode.reindex(px.index).fillna("cash")
    ers_w = ers_w.reindex(px.index).fillna(0.0)
    strong_w = strong_w.reindex(px.index).fillna(0.0)
    best_etf = best_etf.reindex(px.index)
    best_etf = best_etf.fillna(regime_etf)

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
    peak_eq = float(capital)
    dd_halt = False
    dd_reentry = 0
    dd_stop = (
        abs(float(cfg.book_peak_dd_stop))
        if cfg.book_peak_dd_stop is not None and cfg.book_peak_dd_stop > 0
        else None
    )
    reentry_need = max(1, int(cfg.book_dd_reentry_confirm))
    mode_exec = mode.copy()
    halt_flags: list[float] = []
    bench_pick_rows: list[str] = []

    equity_rows: list[float] = []
    trades: list[dict] = []
    eq_index: list[pd.Timestamp] = []

    def _active(weights_row: pd.Series) -> tuple[str | None, float]:
        active = weights_row[weights_row.abs() > 1e-12]
        if len(active) == 0:
            return None, 0.0
        return str(active.index[0]), float(active.iloc[0])

    def _px_open(dt: pd.Timestamp, sym: str, kind: str) -> float:
        if kind == "bench":
            return float(eo.at[dt, sym])
        return float(op.at[dt, sym])

    def _px_close(dt: pd.Timestamp, sym: str, kind: str) -> float:
        if kind == "bench":
            return float(ec.at[dt, sym])
        return float(px.at[dt, sym])

    def _mark(dt: pd.Timestamp) -> float:
        if pos_kind == "cash" or pos_shares <= 0 or pos_sym is None:
            return cash
        return cash + pos_shares * _px_close(dt, pos_sym, pos_kind)

    def _fees_for_kind(kind: str) -> object:
        return bench_fees if kind == "bench" else stock_fees

    def _sell_all(dt: pd.Timestamp, reason: str) -> None:
        nonlocal cash, pos_sym, pos_shares, pos_kind
        if pos_sym is None or pos_shares <= 0:
            return
        kind = pos_kind
        px_o = _px_open(dt, pos_sym, kind)
        if not np.isfinite(px_o) or px_o <= 0:
            return
        notional = pos_shares * px_o
        cost = float(_fees_for_kind(kind).total_cost_usd(notional, px_o))
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
                "kind": kind,
            }
        )
        pos_sym, pos_shares, pos_kind = None, 0.0, "cash"

    def _buy(dt: pd.Timestamp, sym: str, weight: float, reason: str, kind: str) -> None:
        nonlocal cash, pos_sym, pos_shares, pos_kind
        px_o = _px_open(dt, sym, kind)
        if not np.isfinite(px_o) or px_o <= 0:
            return
        shares = float(np.floor(cash * abs(weight) / px_o))
        if shares < 1:
            return
        fee_m = _fees_for_kind(kind)
        notional = shares * px_o
        cost = float(fee_m.total_cost_usd(notional, px_o))
        if notional + cost > cash:
            shares = float(np.floor((cash * 0.999) / px_o))
            if shares < 1:
                return
            notional = shares * px_o
            cost = float(fee_m.total_cost_usd(notional, px_o))
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
                "kind": kind,
            }
        )

    for dt in dates:
        if dt >= start:
            if pending == "cash":
                _sell_all(dt, "to_cash" if not dd_halt else "book_dd_stop")
            elif pending in ("bench", "ers", "strong"):
                kind = pending
                if pos_kind not in ("cash", kind):
                    _sell_all(dt, f"switch_to_{kind}")
                sym, w = target_sym, target_w
                if sym is None or w <= 0:
                    if pos_kind == kind:
                        _sell_all(dt, f"{kind}_flat")
                else:
                    if pos_kind == kind and pos_sym != sym:
                        _sell_all(dt, f"{kind}_rotate")
                    if pos_kind == "cash":
                        _buy(dt, sym, w, f"{kind}_enter", kind)

            eq_index.append(dt)
            marked = _mark(dt)
            equity_rows.append(marked)
            if marked > peak_eq:
                peak_eq = marked
            if dd_stop is not None and peak_eq > 0:
                dd_now = marked / peak_eq - 1.0
                if dd_now <= -dd_stop:
                    dd_halt = True
                    dd_reentry = 0

        m = str(mode.at[dt])
        pick = str(best_etf.at[dt]) if pd.notna(best_etf.at[dt]) else regime_etf
        if pick not in ec.columns:
            pick = regime_etf
        bench_pick_rows.append(pick if m == "bench" else "")

        if m == "cash":
            pending, target_sym, target_w = "cash", None, 0.0
        elif m == "bench":
            pending, target_sym, target_w = "bench", pick, 1.0
        elif m == "strong":
            sym, w = _active(strong_w.loc[dt])
            pending, target_sym, target_w = "strong", sym, w
        else:
            sym, w = _active(ers_w.loc[dt])
            pending, target_sym, target_w = "ers", sym, w

        if dd_halt:
            if m != "cash":
                dd_reentry += 1
            else:
                dd_reentry = 0
            if dd_reentry >= reentry_need:
                dd_halt = False
                dd_reentry = 0
            else:
                pending, target_sym, target_w = "cash", None, 0.0
                mode_exec.at[dt] = "cash"
        halt_flags.append(1.0 if dd_halt else 0.0)

        if dt < start:
            cash = float(capital)
            pos_sym, pos_shares, pos_kind = None, 0.0, "cash"
            peak_eq = float(capital)
            dd_halt = False
            dd_reentry = 0

    idx = pd.DatetimeIndex(eq_index)
    meta = meta.copy()
    meta["book_dd_halt"] = pd.Series(halt_flags, index=mode.index, dtype=float).reindex(meta.index)
    meta["mode_signal"] = mode
    meta["mode"] = mode_exec
    meta["bench_etf"] = pd.Series(bench_pick_rows, index=mode.index, dtype=object).reindex(meta.index)
    meta["best_etf"] = best_etf
    return StructureSimResult(
        equity=pd.Series(equity_rows, index=idx, name="equity"),
        mode=mode_exec.reindex(idx),
        meta=meta.reindex(idx),
        trades=pd.DataFrame(trades),
    )


# Back-compat aliases (deprecated names)
sticky_index_strong_regime = sticky_regime
index_thrust_mask = thrust_mask
crowded_structure_mask = crowded_mask
