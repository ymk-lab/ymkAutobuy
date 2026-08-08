"""Market Regime Label scorecard + hysteresis (ADR-0009)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

RegimeLabel = Literal[
    "Defense",
    "Range",
    "Rotation",
    "CrowdedTrend",
    "PanicRebound",
]

LABELS: tuple[RegimeLabel, ...] = (
    "Defense",
    "PanicRebound",
    "CrowdedTrend",
    "Rotation",
    "Range",
)

# Tie-break priority (earlier wins)
TIE_PRIORITY: tuple[RegimeLabel, ...] = (
    "Defense",
    "PanicRebound",
    "CrowdedTrend",
    "Rotation",
    "Range",
)


@dataclass
class RegimeScorecardConfig:
    sma_fast: int = 50
    sma_slow: int = 200
    already_strong_cap: float = 0.10
    top_k: int = 10
    peak_lookback: int = 60
    defense_dd: float = 0.08
    defense_ret20: float = -0.03
    range_ret20_abs: float = 0.03
    crowded_overlap: float = 0.50
    crowded_strong_share: float = 0.25
    # If False: CrowdedTrend leadership test is overlap OR strong_share (still needs trend context).
    crowded_require_both: bool = True
    rotation_overlap_max: float = 0.40
    rotation_strong_max: float = 0.20
    panic_dd: float = 0.10
    panic_bounce_days: int = 5
    panic_bounce_min: float = 0.04
    leave_defense_confirm: int = 5
    attack_switch_confirm: int = 3


def crowded_trend_relaxed_config() -> RegimeScorecardConfig:
    """Fully looser CrowdedTrend + milder Defense (theme bull legs, e.g. SMH)."""
    return RegimeScorecardConfig(
        crowded_overlap=0.40,
        crowded_strong_share=0.15,
        crowded_require_both=False,
        # Slightly less hair-trigger Defense so CrowdedTrend can stick through shallow dips.
        defense_dd=0.12,
        defense_ret20=-0.05,
        leave_defense_confirm=3,
    )


def crowded_trend_params_relaxed() -> RegimeScorecardConfig:
    """Relax *only* CrowdedTrend leadership tests; keep Defense/hysteresis defaults."""
    return RegimeScorecardConfig(
        crowded_overlap=0.40,
        crowded_strong_share=0.15,
        crowded_require_both=False,
    )


def market_crowded_relaxed_mask(
    qqq_close: pd.Series,
    member_closes: pd.DataFrame,
    *,
    base_config: RegimeScorecardConfig | None = None,
    crowded_config: RegimeScorecardConfig | None = None,
) -> pd.Series:
    """True when the bench still qualifies as Crowded under *relaxed* thresholds.

    Used to *extend* an existing CrowdedTrend stay (not to enter). Leadership uses
    relaxed levels but still requires **both** overlap and strong_share (AND), so
    OR-churn cannot convert a long Rotation leg into QQQ hold.

    Risk gates stay strict (``base_config`` Defense).
    """
    base = base_config or RegimeScorecardConfig()
    crowd = crowded_config or crowded_trend_params_relaxed()
    _scores, meta = score_regimes(qqq_close, member_closes, config=crowd)
    above50 = meta["above_sma50"] > 0.5
    # Persistence: AND at relaxed thresholds (0.40 / 0.15), ignore require_both=False
    leadership = (meta["overlap"] >= crowd.crowded_overlap) & (
        meta["strong_share"] >= crowd.crowded_strong_share
    )
    hard_defense = (
        (~above50)
        | (meta["dd60"] <= -base.defense_dd)
        | (meta["ret20"] <= base.defense_ret20)
    )
    return (above50 & leadership & ~hard_defense).fillna(False).astype(bool)


def apply_market_crowded_relax_gate(
    raw_strict: pd.Series,
    market_crowded: pd.Series,
) -> pd.Series:
    """Legacy upgrade: force CrowdedTrend on all attack labels while mask is true.

    Prefer ``apply_crowded_relaxed_persistence`` — enter Crowded only on strict
    labels, then stay while the relaxed 大盤 mask holds.
    """
    out = raw_strict.astype(str).copy()
    crowd = market_crowded.reindex(out.index).fillna(False).astype(bool)
    upgradable = ~out.isin(["Defense", "PanicRebound"])
    out.loc[crowd & upgradable] = "CrowdedTrend"
    out.name = "raw_label"
    return out


def apply_crowded_relaxed_persistence(
    raw_strict: pd.Series,
    market_crowded: pd.Series,
) -> pd.Series:
    """Strict CrowdedTrend *entry*; relaxed leadership only extends the stay.

    - Enter CrowdedTrend only when ``raw_strict`` says so (strict tests).
    - Once in CrowdedTrend, remain while ``market_crowded`` (relaxed leadership)
      and not Defense/PanicRebound.
    - Defense / PanicRebound always break the stay immediately.
    """
    strict = raw_strict.astype(str)
    lead = market_crowded.reindex(strict.index).fillna(False).astype(bool)
    out: list[str] = []
    in_crowd = False
    for lab, ok in zip(strict.tolist(), lead.tolist()):
        if lab in ("Defense", "PanicRebound"):
            in_crowd = False
            out.append(lab)
            continue
        if lab == "CrowdedTrend":
            in_crowd = True
            out.append("CrowdedTrend")
            continue
        if in_crowd and ok:
            out.append("CrowdedTrend")
            continue
        in_crowd = False
        out.append(lab)
    return pd.Series(out, index=strict.index, name="raw_label")


def _top_set(row: pd.Series, k: int) -> set[str]:
    s = row.replace([np.inf, -np.inf], np.nan).dropna()
    if s.empty:
        return set()
    return set(s.nlargest(min(k, len(s))).index.astype(str))


def _overlap_ratio(a: set[str], b: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    if not a and not b:
        return 0.0
    return len(a & b) / float(k)


def score_regimes(
    qqq_close: pd.Series,
    member_closes: pd.DataFrame,
    *,
    config: RegimeScorecardConfig | None = None,
) -> pd.DataFrame:
    """Return daily score columns for each RegimeLabel (0..~3 scale)."""
    cfg = config or RegimeScorecardConfig()
    bench = qqq_close.astype(float).sort_index()
    px = member_closes.astype(float).reindex(bench.index).ffill()

    sma50 = bench.rolling(cfg.sma_fast, min_periods=cfg.sma_fast).mean()
    sma200 = bench.rolling(cfg.sma_slow, min_periods=cfg.sma_slow).mean()
    ret5 = bench / bench.shift(5) - 1.0
    ret20 = bench / bench.shift(20) - 1.0
    peak = bench.rolling(cfg.peak_lookback, min_periods=20).max()
    dd = bench / peak - 1.0

    # Member relative / absolute features
    stock_ret20 = px / px.shift(20) - 1.0
    stock_ret60 = px / px.shift(60) - 1.0
    bench_ret20 = bench / bench.shift(20) - 1.0
    bench_ret60 = bench / bench.shift(60) - 1.0
    ex60 = stock_ret60.sub(bench_ret60, axis=0)
    strong = ex60 > cfg.already_strong_cap
    strong_share = strong.sum(axis=1) / strong.count(axis=1).clip(lower=1)
    breadth = (stock_ret20 > 0).sum(axis=1) / stock_ret20.count(axis=1).clip(lower=1)

    overlap = []
    for dt in px.index:
        a = _top_set(stock_ret20.loc[dt], cfg.top_k)
        b = _top_set(stock_ret60.loc[dt], cfg.top_k)
        overlap.append(_overlap_ratio(a, b, cfg.top_k))
    overlap_s = pd.Series(overlap, index=px.index, dtype=float)

    # Panic: was deep dd recently, now bouncing
    dd_min_10 = dd.rolling(10, min_periods=3).min()
    bounce = bench / bench.shift(cfg.panic_bounce_days) - 1.0

    scores = pd.DataFrame(index=bench.index, columns=list(LABELS), dtype=float)
    above50 = bench > sma50
    above200 = bench > sma200

    # Defense
    scores["Defense"] = 0.0
    scores.loc[~above50.fillna(False), "Defense"] += 1.5
    scores.loc[dd <= -cfg.defense_dd, "Defense"] += 1.0
    scores.loc[ret20 <= cfg.defense_ret20, "Defense"] += 0.8
    scores.loc[(~above200.fillna(False)) & (~above50.fillna(False)), "Defense"] += 0.5

    # PanicRebound
    scores["PanicRebound"] = 0.0
    panic_mask = (dd_min_10 <= -cfg.panic_dd) & (bounce >= cfg.panic_bounce_min)
    scores.loc[panic_mask.fillna(False), "PanicRebound"] += 2.0
    scores.loc[panic_mask.fillna(False) & (~above50.fillna(False)), "PanicRebound"] += 0.5
    scores.loc[panic_mask.fillna(False) & (ret5 > 0), "PanicRebound"] += 0.3

    # Range
    scores["Range"] = 0.0
    near_ma = (bench / sma50 - 1.0).abs() <= 0.02
    scores.loc[near_ma.fillna(False), "Range"] += 1.0
    scores.loc[ret20.abs() <= cfg.range_ret20_abs, "Range"] += 1.0
    scores.loc[(breadth - 0.5).abs() <= 0.15, "Range"] += 0.5
    scores.loc[above50.fillna(False) & near_ma.fillna(False), "Range"] += 0.3

    # Rotation
    scores["Rotation"] = 0.0
    scores.loc[above50.fillna(False), "Rotation"] += 1.2
    scores.loc[overlap_s <= cfg.rotation_overlap_max, "Rotation"] += 1.0
    scores.loc[strong_share <= cfg.rotation_strong_max, "Rotation"] += 1.0
    scores.loc[breadth >= 0.45, "Rotation"] += 0.4
    scores.loc[above200.fillna(False), "Rotation"] += 0.3

    # CrowdedTrend (leadership concentration; AND/OR via crowded_require_both)
    scores["CrowdedTrend"] = 0.0
    scores.loc[above50.fillna(False), "CrowdedTrend"] += 1.0
    ov_ok = overlap_s >= cfg.crowded_overlap
    ss_ok = strong_share >= cfg.crowded_strong_share
    crowd_hit = (ov_ok & ss_ok) if cfg.crowded_require_both else (ov_ok | ss_ok)
    scores.loc[crowd_hit.fillna(False), "CrowdedTrend"] += 2.0
    scores.loc[ov_ok.fillna(False), "CrowdedTrend"] += 0.4
    scores.loc[ss_ok.fillna(False), "CrowdedTrend"] += 0.4
    scores.loc[ret20 >= 0.05, "CrowdedTrend"] += 0.3
    # Extra: clear uptrend while above SMA50 favors Crowded over Rotation
    scores.loc[above50.fillna(False) & (ret20 >= 0.03), "CrowdedTrend"] += 0.5

    scores = scores.fillna(0.0)
    meta = pd.DataFrame(
        {
            "above_sma50": above50.fillna(False).astype(float),
            "above_sma200": above200.fillna(False).astype(float),
            "ret20": ret20,
            "dd60": dd,
            "overlap": overlap_s,
            "strong_share": strong_share,
            "breadth": breadth,
        },
        index=bench.index,
    )
    return scores, meta


def raw_labels_from_scores(scores: pd.DataFrame) -> pd.Series:
    """Argmax with fixed tie-break priority."""
    pri = {lab: i for i, lab in enumerate(TIE_PRIORITY)}
    out: list[str] = []
    for dt in scores.index:
        row = scores.loc[dt]
        best = -1e18
        pick: RegimeLabel = "Range"
        for lab in TIE_PRIORITY:
            v = float(row.get(lab, 0.0))
            # higher score wins; tie → earlier in TIE_PRIORITY
            if v > best + 1e-12:
                best = v
                pick = lab  # type: ignore[assignment]
            elif abs(v - best) <= 1e-12 and pri[lab] < pri[pick]:
                pick = lab  # type: ignore[assignment]
        out.append(pick)
    return pd.Series(out, index=scores.index, name="raw_label")


def apply_hysteresis(
    raw: pd.Series,
    *,
    config: RegimeScorecardConfig | None = None,
) -> pd.Series:
    cfg = config or RegimeScorecardConfig()
    labels: list[str] = []
    active: str | None = None
    pending: str | None = None
    pending_count = 0

    attack = {"Range", "Rotation", "CrowdedTrend", "PanicRebound"}

    for lab in raw.astype(str):
        if active is None:
            active = lab
            pending = None
            pending_count = 0
            labels.append(active)
            continue

        if lab == active:
            pending = None
            pending_count = 0
            labels.append(active)
            continue

        # Immediate enter Defense
        if lab == "Defense":
            active = "Defense"
            pending = None
            pending_count = 0
            labels.append(active)
            continue

        need = (
            cfg.leave_defense_confirm
            if active == "Defense"
            else cfg.attack_switch_confirm
            if active in attack and lab in attack
            else cfg.attack_switch_confirm
        )

        if pending != lab:
            pending = lab
            pending_count = 1
        else:
            pending_count += 1

        if pending_count >= need:
            active = pending
            pending = None
            pending_count = 0
        labels.append(active)

    return pd.Series(labels, index=raw.index, name="label")


def hierarchy_raw_labels(
    qqq_close: pd.Series,
    member_closes: pd.DataFrame,
    *,
    config: RegimeScorecardConfig | None = None,
) -> tuple[pd.Series, pd.DataFrame]:
    """Risk-first cascade (ADR-0009 option A): Defense → Panic → Crowded → Rotation → Range."""
    cfg = config or RegimeScorecardConfig()
    _scores, meta = score_regimes(qqq_close, member_closes, config=cfg)
    above50 = meta["above_sma50"] > 0.5
    dd = meta["dd60"]
    ret20 = meta["ret20"]
    overlap = meta["overlap"]
    strong = meta["strong_share"]
    bounce = qqq_close.astype(float) / qqq_close.astype(float).shift(cfg.panic_bounce_days) - 1.0
    dd_min_10 = dd.rolling(10, min_periods=3).min()

    raw: list[str] = []
    for dt in meta.index:
        a50 = bool(above50.loc[dt]) if dt in above50.index else False
        ddv = float(dd.loc[dt]) if np.isfinite(float(dd.loc[dt])) else 0.0
        r20 = float(ret20.loc[dt]) if np.isfinite(float(ret20.loc[dt])) else 0.0
        ov = float(overlap.loc[dt]) if np.isfinite(float(overlap.loc[dt])) else 0.0
        ss = float(strong.loc[dt]) if np.isfinite(float(strong.loc[dt])) else 0.0
        bnc = float(bounce.loc[dt]) if dt in bounce.index and np.isfinite(float(bounce.loc[dt])) else 0.0
        dmin = float(dd_min_10.loc[dt]) if dt in dd_min_10.index and np.isfinite(float(dd_min_10.loc[dt])) else 0.0

        # 1) Panic override (even if below MA): recent washout + bounce
        if dmin <= -cfg.panic_dd and bnc >= cfg.panic_bounce_min:
            raw.append("PanicRebound")
            continue
        # 2) Defense
        if (not a50) or (ddv <= -cfg.defense_dd) or (r20 <= cfg.defense_ret20):
            raw.append("Defense")
            continue
        # 3) CrowdedTrend (AND or OR per config)
        ov_ok = ov >= cfg.crowded_overlap
        ss_ok = ss >= cfg.crowded_strong_share
        crowd_hit = (ov_ok and ss_ok) if cfg.crowded_require_both else (ov_ok or ss_ok)
        if a50 and crowd_hit:
            raw.append("CrowdedTrend")
            continue
        # Risk-on uptrend default → Crowded when above SMA50 and rising (relaxed path)
        if a50 and (not cfg.crowded_require_both) and r20 >= 0.03:
            raw.append("CrowdedTrend")
            continue
        # 4) Rotation vs Range
        if ov <= cfg.rotation_overlap_max and ss <= cfg.rotation_strong_max:
            raw.append("Rotation")
            continue
        if abs(r20) <= cfg.range_ret20_abs:
            raw.append("Range")
            continue
        # Default risk-on without clear crowd → Rotation
        raw.append("Rotation")
    return pd.Series(raw, index=meta.index, name="raw_label"), meta


def label_regimes(
    qqq_close: pd.Series,
    member_closes: pd.DataFrame,
    *,
    config: RegimeScorecardConfig | None = None,
    method: str = "scorecard",
    market_crowded_relax: bool = False,
) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    """Return (hysteresis labels, scores, meta features).

    ``method``: ``scorecard`` (default) or ``hierarchy`` (risk-first cascade).

    ``market_crowded_relax``: strict CrowdedTrend entry; relaxed leadership only
    keeps an existing CrowdedTrend (大盤已是 Crowded 時才寬鬆續持). Does not
    convert Rotation→Crowded on its own.
    """
    cfg = config or RegimeScorecardConfig()
    scores, meta = score_regimes(qqq_close, member_closes, config=cfg)
    if method == "hierarchy":
        raw, meta_h = hierarchy_raw_labels(qqq_close, member_closes, config=cfg)
        meta = meta_h
    elif method == "scorecard":
        raw = raw_labels_from_scores(scores)
    else:
        raise ValueError(f"unknown regime method: {method}")
    market_crowd = pd.Series(False, index=raw.index)
    if market_crowded_relax:
        market_crowd = market_crowded_relaxed_mask(
            qqq_close, member_closes, base_config=cfg
        ).reindex(raw.index).fillna(False)
        raw = apply_crowded_relaxed_persistence(raw, market_crowd)
    labels = apply_hysteresis(raw, config=cfg)
    meta = meta.copy()
    meta["raw_label"] = raw
    meta["label"] = labels
    meta["method"] = method
    meta["market_crowded_relax"] = bool(market_crowded_relax)
    meta["market_crowded"] = market_crowd.astype(float)
    return labels, scores, meta
