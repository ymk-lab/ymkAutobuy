#!/usr/bin/env python3
"""V13 Experiment 1 — 2022 full-year bear-market extrapolation stress.

Goal
----
Verify whether defense / thrust priority (``thrust > harsh_dd``,
``thrust_force_bench``) causes *massive* drawdowns in a unilateral decline
with repeated dead-cat bounces.

Protocol
--------
- Window: 2022-01-01 → 2023-01-01 (OOS vs v13 tune windows 2023 / 2025–2026)
- Production weights: SPY 50% / QQQ 50% (``V13_BOOK_WEIGHTS``)
- Capital $50k, Futu fees + 3bps, next-open
- Yahoo OHLCV bootstrap 2019-01 → 2023-06 into a dedicated cache

Ablations (same v13 knobs except thrust priority levers)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
1. ``v13_baseline`` — production (thrust overrides harsh_dd; force bench)
2. ``no_thrust_over_harsh`` — ``thrust_overrides_dd_harsh=False``
3. ``no_thrust_force`` — ``thrust_force_bench=False``
4. ``thrust_demoted`` — both False (thrust cannot lock bench)

Pass / fail (pre-registered)
----------------------------
- **FAIL** if turning off ``thrust_overrides_dd_harsh`` improves maxDD by ≥5pp
  (priority order materially worsened the bear).
- **FAIL** if baseline maxDD is ≥20pp worse than SPY B&H *and* mean forward
  10d bench return on ``thrust ∩ harsh_dd`` days is negative.
- **PASS** if the harsh-override ablation improves maxDD by <3pp
  (thrust priority is not the main DD driver).
- **CONDITIONAL** otherwise (report deltas; do not change production).
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.data.loader import validate_ohlcv
from qresearch.strategy.regime_playbook import simulate_bench_bh
from qresearch.strategy.structure_gate import (
    V13_BOOK_WEIGHTS,
    StructureGateConfig,
    blend_structure_gate_books,
)
from run_emerging_rs_wave_gates import metrics  # type: ignore
from run_structure_gate_bakeoff import soft_pass  # type: ignore
from run_structure_gate_v13_blend import (  # type: ignore
    CAPITAL,
    book_members,
    run_book,
)

OUT = ROOT / "examples" / "data" / "structure_gate_v13_exp1_2022_bear"
CACHE = OUT / "cache_ohlcv_2019"
YF_START = "2019-01-01"
YF_END = "2023-06-01"
MIN_BARS = 220
WEIGHTS = dict(V13_BOOK_WEIGHTS)
START = pd.Timestamp("2022-01-01")
END = pd.Timestamp("2023-01-01")

# Pre-registered thresholds (see module docstring).
PASS_MAXDD_IMPROVE_LT_PP = 3.0
FAIL_MAXDD_IMPROVE_GE_PP = 5.0
FAIL_VS_SPY_DD_GE_PP = 20.0


def _normalize_yf(raw: pd.DataFrame) -> pd.DataFrame | None:
    if raw is None or len(raw) < MIN_BARS:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.copy()
        raw.columns = [str(c[0]).lower() for c in raw.columns]
    else:
        raw = raw.copy()
        raw.columns = [str(c).lower() for c in raw.columns]
    need = ["open", "high", "low", "close", "volume"]
    if any(c not in raw.columns for c in need):
        return None
    df = validate_ohlcv(raw[need].dropna())
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[~df.index.duplicated(keep="last")].sort_index()


def bootstrap_cache(symbols: list[str]) -> None:
    import yfinance as yf

    CACHE.mkdir(parents=True, exist_ok=True)
    missing = [s for s in symbols if not (CACHE / f"{s}.csv").is_file()]
    print(
        f"cache={CACHE} present={len(symbols) - len(missing)} missing={len(missing)}",
        flush=True,
    )
    if not missing:
        return

    chunk = 40
    for i in range(0, len(missing), chunk):
        batch = missing[i : i + chunk]
        print(f"yf batch {i + 1}-{i + len(batch)} / {len(missing)}: {batch[:5]}…", flush=True)
        try:
            raw = yf.download(
                batch,
                start=YF_START,
                end=YF_END,
                auto_adjust=True,
                progress=False,
                threads=True,
                group_by="ticker",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  batch failed: {exc}", flush=True)
            raw = None

        for sym in batch:
            path = CACHE / f"{sym}.csv"
            df = None
            if raw is not None and len(batch) > 1:
                try:
                    if isinstance(raw.columns, pd.MultiIndex) and sym in raw.columns.get_level_values(0):
                        sub = raw[sym].dropna(how="all")
                        df = _normalize_yf(sub)
                except Exception:
                    df = None
            elif raw is not None and len(batch) == 1:
                df = _normalize_yf(raw)

            if df is None:
                try:
                    one = yf.download(
                        sym,
                        start=YF_START,
                        end=YF_END,
                        auto_adjust=True,
                        progress=False,
                        threads=False,
                    )
                    df = _normalize_yf(one)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {sym} fail: {exc}", flush=True)
                    continue
            if df is not None and len(df) >= MIN_BARS:
                df.to_csv(path)
            else:
                print(f"  {sym} skip bars={0 if df is None else len(df)}", flush=True)
        time.sleep(0.35)


def load_from_cache(symbols: list[str]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols, 1):
        path = CACHE / f"{sym}.csv"
        if path.is_file():
            try:
                raw = pd.read_csv(path, index_col=0, parse_dates=True)
                raw.columns = [str(c).lower() for c in raw.columns]
                df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
                df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
                df = df[~df.index.duplicated(keep="last")].sort_index()
                if len(df) >= MIN_BARS:
                    frames[sym] = df
            except Exception:
                pass
        if i == 1 or i % 80 == 0 or i == len(symbols):
            print(f"load [{i}/{len(symbols)}] ok={len(frames)}", flush=True)
    return frames


def variant_configs() -> dict[str, StructureGateConfig]:
    base = StructureGateConfig.v13()
    return {
        "v13_baseline": base,
        "no_thrust_over_harsh": replace(base, thrust_overrides_dd_harsh=False),
        "no_thrust_force": replace(base, thrust_force_bench=False),
        "thrust_demoted": replace(
            base, thrust_overrides_dd_harsh=False, thrust_force_bench=False
        ),
    }


def _flag(series: pd.Series) -> pd.Series:
    return series.fillna(0.0).astype(float) > 0.5


def dead_cat_mask(meta: pd.DataFrame) -> pd.Series:
    """Short bounce while still structurally weak (below SMA50 or deep dd60)."""
    below50 = meta["above_sma50"].fillna(1.0).astype(float) < 0.5
    deep_dd = meta["dd60"].fillna(0.0).astype(float) <= -0.10
    weak = below50 | deep_dd
    bounce = (
        (meta["ret5"].fillna(0.0) >= 0.03)
        | (meta["ret10"].fillna(0.0) >= 0.05)
        | (meta["bounce20"].fillna(0.0) >= 0.04)
    )
    return (weak & bounce).fillna(False)


def forward_returns(close: pd.Series, days: int) -> pd.Series:
    return close.shift(-days) / close - 1.0


def audit_sleeve_meta(meta: pd.DataFrame, bench_close: pd.Series) -> dict:
    m = meta.reindex(meta.index.intersection(bench_close.index)).copy()
    if m.empty:
        return {"n_days": 0}

    thrust = _flag(m["thrust"])
    thrust_raw = _flag(m.get("thrust_raw", m["thrust"]))
    harsh_dd = _flag(m["harsh_dd"])
    harsh_ret = _flag(m["harsh_ret"])
    sticky = _flag(m["sticky"])
    mode = m["mode"].astype(str)
    dcb = dead_cat_mask(m)

    conflict = thrust & harsh_dd  # days where thrust>harsh_dd priority matters
    thrust_on_dcb = thrust & dcb
    bench_on_dcb = (mode == "bench") & dcb
    cash_share = float((mode == "cash").mean())
    thrust_share = float(thrust.mean())
    harsh_dd_share = float(harsh_dd.mean())
    conflict_share = float(conflict.mean())
    dcb_share = float(dcb.mean())

    fwd = {}
    for h in (5, 10, 20):
        fr = forward_returns(bench_close.reindex(m.index).ffill(), h)
        fwd[f"mean_fwd{h}_on_thrust_harsh"] = (
            float(fr[conflict].mean()) if conflict.any() else float("nan")
        )
        fwd[f"mean_fwd{h}_on_thrust_dcb"] = (
            float(fr[thrust_on_dcb].mean()) if thrust_on_dcb.any() else float("nan")
        )
        fwd[f"mean_fwd{h}_on_dcb"] = float(fr[dcb].mean()) if dcb.any() else float("nan")

    # Episode starts: first day of a thrust∩dcb run
    episode = thrust_on_dcb.astype(int).diff().fillna(0).eq(1)
    ep_fwd10 = forward_returns(bench_close.reindex(m.index).ffill(), 10)
    ep_rets = ep_fwd10[episode]
    return {
        "n_days": int(len(m)),
        "cash_share": cash_share,
        "bench_share": float((mode == "bench").mean()),
        "ers_share": float((mode == "ers").mean()),
        "strong_share": float((mode == "strong").mean()),
        "thrust_lock_share": thrust_share,
        "thrust_raw_share": float(thrust_raw.mean()),
        "harsh_dd_share": harsh_dd_share,
        "harsh_ret_share": float(harsh_ret.mean()),
        "sticky_share": float(sticky.mean()),
        "dead_cat_share": dcb_share,
        "thrust_x_harsh_dd_share": conflict_share,
        "thrust_x_dead_cat_share": float(thrust_on_dcb.mean()),
        "bench_on_dead_cat_share": float(bench_on_dcb.mean()),
        "n_thrust_dead_cat_episodes": int(episode.sum()),
        "mean_fwd10_after_thrust_dcb_episode": (
            float(ep_rets.mean()) if len(ep_rets) else float("nan")
        ),
        **fwd,
        "mode_distribution": mode.value_counts(normalize=True).to_dict(),
    }


def run_variant(
    frames: dict[str, pd.DataFrame],
    cfg: StructureGateConfig,
    *,
    label: str,
) -> dict:
    book_sims = {}
    sleeve_rows = []
    audits = {}
    print(f"\n=== {label} {START.date()}→{END.date()} weights={WEIGHTS} ===", flush=True)
    for book, w in WEIGHTS.items():
        sleeve_cap = CAPITAL * w
        sim, bh, n_mem = run_book(
            book, frames, sleeve_capital=sleeve_cap, start=START, end=END, cfg=cfg
        )
        book_sims[book] = sim
        m = metrics(sim.equity, sleeve_cap)
        mb = metrics(bh, sleeve_cap)
        meta = sim.meta
        if meta is not None and len(meta):
            meta_w = meta.loc[START:END]
            audit = audit_sleeve_meta(meta_w, frames[book]["close"])
        else:
            audit = {"n_days": 0}
        audits[book] = audit
        row = {
            "book": book,
            "weight": w,
            "n_members": n_mem,
            "total_return": m["total_return"],
            "max_drawdown": m["max_drawdown"],
            "sharpe": m["sharpe"],
            "bh_total_return": mb["total_return"],
            "n_trades": int(len(sim.trades)),
            "mode_distribution": sim.mode.loc[START:END].value_counts(normalize=True).to_dict()
            if len(sim.mode)
            else {},
            "audit": audit,
        }
        sleeve_rows.append(row)
        print(
            f"  {book:4} SG={m['total_return']*100:7.2f}% BH={mb['total_return']*100:6.2f}% "
            f"maxDD={m['max_drawdown']*100:6.2f}% thrust={audit.get('thrust_lock_share', 0)*100:4.1f}% "
            f"thrust∩harsh={audit.get('thrust_x_harsh_dd_share', 0)*100:4.1f}% "
            f"dcb={audit.get('dead_cat_share', 0)*100:4.1f}% trades={row['n_trades']}",
            flush=True,
        )
        sim.equity.to_csv(OUT / f"equity_{label}_{book}.csv", header=["equity"])
        if meta is not None and len(meta):
            cols = [
                c
                for c in (
                    "mode",
                    "thrust",
                    "thrust_raw",
                    "harsh_dd",
                    "harsh_ret",
                    "sticky",
                    "mild",
                    "ret5",
                    "ret10",
                    "ret20",
                    "bounce20",
                    "dd60",
                    "above_sma50",
                )
                if c in meta.columns
            ]
            meta.loc[START:END, cols].to_csv(OUT / f"meta_{label}_{book}.csv")

    blended, panel = blend_structure_gate_books(book_sims, WEIGHTS, capital=CAPITAL)
    blended = blended.loc[START:END].dropna()
    panel = panel.reindex(blended.index).ffill()
    m_b = metrics(blended, CAPITAL)

    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    spy = frames["SPY"]
    eq_bh = (
        simulate_bench_bh(spy["open"], spy["close"], capital=CAPITAL, start=START, fees=fees)
        .reindex(blended.index)
        .ffill()
    )
    m_bh = metrics(eq_bh, CAPITAL)

    etf_eq = []
    for book, w in WEIGHTS.items():
        bdf = frames[book]
        etf_eq.append(
            simulate_bench_bh(
                bdf["open"], bdf["close"], capital=CAPITAL * w, start=START, fees=fees
            )
        )
    static = pd.concat(etf_eq, axis=1).ffill().sum(axis=1).reindex(blended.index).ffill()
    m_static = metrics(static, CAPITAL)
    gate = soft_pass(m_b["total_return"], m_bh["total_return"], m_static["total_return"])

    blended.to_csv(OUT / f"equity_{label}_blend.csv", header=["equity"])
    out = {
        "label": label,
        "start": str(START.date()),
        "end": str(END.date()),
        "weights": WEIGHTS,
        "config": {
            "thrust_overrides_dd_harsh": bool(cfg.thrust_overrides_dd_harsh),
            "thrust_force_bench": bool(cfg.thrust_force_bench),
            "preset": "v13",
        },
        "blend": {
            "total_return": m_b["total_return"],
            "max_drawdown": m_b["max_drawdown"],
            "sharpe": m_b["sharpe"],
            "end_equity": m_b["end_equity"],
            "vs_spy_bh_pp": (m_b["total_return"] - m_bh["total_return"]) * 100,
            "vs_static_etf_blend_pp": (m_b["total_return"] - m_static["total_return"]) * 100,
            "n_trades": int(sum(r["n_trades"] for r in sleeve_rows)),
        },
        "spy_bh": m_bh,
        "static_etf_blend": m_static,
        "soft_pass": gate,
        "sleeves": sleeve_rows,
        "audits": audits,
    }
    print(
        f"  BLEND  ret={m_b['total_return']*100:7.2f}% maxDD={m_b['max_drawdown']*100:6.2f}% "
        f"vsSPY={out['blend']['vs_spy_bh_pp']:+.1f}pp vsStatic={out['blend']['vs_static_etf_blend_pp']:+.1f}pp",
        flush=True,
    )
    return out


def _pp(x: float | None, digits: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{100.0 * float(x):+.{digits}f}%"


def _fpp(x: float | None, digits: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{float(x):+.{digits}f}pp"


def judge(results: dict[str, dict]) -> dict:
    base = results["v13_baseline"]["blend"]
    no_over = results["no_thrust_over_harsh"]["blend"]
    demoted = results["thrust_demoted"]["blend"]
    spy_dd = results["v13_baseline"]["spy_bh"]["max_drawdown"]

    # maxDD is negative; "improve" = less negative = larger algebraically
    improve_over_pp = (no_over["max_drawdown"] - base["max_drawdown"]) * 100
    improve_demoted_pp = (demoted["max_drawdown"] - base["max_drawdown"]) * 100
    vs_spy_dd_pp = (base["max_drawdown"] - spy_dd) * 100  # more negative → worse

    # Weight-average forward 10d on thrust∩harsh across sleeves
    audits = results["v13_baseline"]["audits"]
    fwd_vals = []
    for book, w in WEIGHTS.items():
        v = audits.get(book, {}).get("mean_fwd10_on_thrust_harsh")
        if v is not None and np.isfinite(v):
            fwd_vals.append((w, float(v)))
    mean_fwd10 = (
        float(sum(w * v for w, v in fwd_vals) / sum(w for w, _ in fwd_vals))
        if fwd_vals
        else float("nan")
    )

    reasons = []
    verdict = "PASS"

    if improve_over_pp >= FAIL_MAXDD_IMPROVE_GE_PP:
        verdict = "FAIL"
        reasons.append(
            f"關閉 thrust_overrides_dd_harsh 使 maxDD 改善 {improve_over_pp:.2f}pp ≥ "
            f"{FAIL_MAXDD_IMPROVE_GE_PP}pp → 優先序在熊市造成可測得多餘回撤"
        )
    if vs_spy_dd_pp <= -FAIL_VS_SPY_DD_GE_PP and (
        np.isfinite(mean_fwd10) and mean_fwd10 < 0
    ):
        verdict = "FAIL"
        reasons.append(
            f"baseline maxDD 比 SPY 差 {abs(vs_spy_dd_pp):.2f}pp ≥ {FAIL_VS_SPY_DD_GE_PP}pp，"
            f"且 thrust∩harsh_dd 日後 10 日基準均報酬 {mean_fwd10*100:.2f}% < 0"
        )

    if verdict != "FAIL":
        if improve_over_pp < PASS_MAXDD_IMPROVE_LT_PP:
            verdict = "PASS"
            reasons.append(
                f"關閉 thrust 蓋過 harsh_dd 僅改善 maxDD {improve_over_pp:.2f}pp < "
                f"{PASS_MAXDD_IMPROVE_LT_PP}pp → 優先序不是巨額回撤主因"
            )
        else:
            verdict = "CONDITIONAL"
            reasons.append(
                f"關閉 override 改善 maxDD {improve_over_pp:.2f}pp，介於 "
                f"{PASS_MAXDD_IMPROVE_LT_PP}–{FAIL_MAXDD_IMPROVE_GE_PP}pp；不改 production，需人工解讀"
            )

    return {
        "verdict": verdict,
        "reasons": reasons,
        "metrics": {
            "baseline_maxdd": base["max_drawdown"],
            "baseline_ret": base["total_return"],
            "spy_bh_maxdd": spy_dd,
            "spy_bh_ret": results["v13_baseline"]["spy_bh"]["total_return"],
            "improve_maxdd_no_thrust_over_harsh_pp": improve_over_pp,
            "improve_maxdd_thrust_demoted_pp": improve_demoted_pp,
            "baseline_vs_spy_maxdd_pp": vs_spy_dd_pp,
            "mean_fwd10_on_thrust_harsh": mean_fwd10,
        },
        "thresholds": {
            "pass_maxdd_improve_lt_pp": PASS_MAXDD_IMPROVE_LT_PP,
            "fail_maxdd_improve_ge_pp": FAIL_MAXDD_IMPROVE_GE_PP,
            "fail_vs_spy_dd_ge_pp": FAIL_VS_SPY_DD_GE_PP,
        },
    }


def write_reports(results: dict[str, dict], decision: dict, n_symbols: int) -> None:
    summary = {
        "ok": True,
        "experiment": "v13_exp1_2022_bear",
        "goal_zh": "驗證單邊下跌與多次死貓跳中，防禦與 thrust 優先序是否造成巨額回撤",
        "window": {"start": str(START.date()), "end": str(END.date())},
        "weights": WEIGHTS,
        "capital": CAPITAL,
        "data": {
            "cache": str(CACHE),
            "yf_start": YF_START,
            "yf_end": YF_END,
            "n_symbols": n_symbols,
        },
        "note": "OOS vs v13 tune (2023 / 2025-08→2026-08); production SPY50/QQQ50",
        "variants": results,
        "decision": decision,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float) + "\n")

    lines_en = [
        "=== V13 Experiment 1 — 2022 full-year bear stress (SPY50/QQQ50) ===",
        f"data: Yahoo {YF_START}→{YF_END}, symbols_ok={n_symbols}",
        "capital $50k | SPY50/QQQ50 | Futu fees+3bps | next-open | OOS vs v13 tune",
        "",
        f"VERDICT: {decision['verdict']}",
    ]
    for r in decision["reasons"]:
        lines_en.append(f"  - {r}")
    lines_en.append("")
    spy = results["v13_baseline"]["spy_bh"]
    static = results["v13_baseline"]["static_etf_blend"]
    lines_en.append(
        f"SPY B&H: {_pp(spy['total_return'])} maxDD={_pp(spy['max_drawdown'])} | "
        f"static 50/50: {_pp(static['total_return'])} maxDD={_pp(static['max_drawdown'])}"
    )
    lines_en.append("")
    for label, rep in results.items():
        b = rep["blend"]
        lines_en.append(
            f"{label:22} ret={_pp(b['total_return']):>9} maxDD={_pp(b['max_drawdown']):>9} "
            f"sharpe={b['sharpe']:6.2f} vsSPY={_fpp(b['vs_spy_bh_pp'])} "
            f"vsStatic={_fpp(b['vs_static_etf_blend_pp'])} trades={b['n_trades']}"
        )
        for s in rep["sleeves"]:
            a = s["audit"]
            lines_en.append(
                f"  {s['book']:4} ret={_pp(s['total_return']):>9} maxDD={_pp(s['max_drawdown']):>9} "
                f"thrust={a.get('thrust_lock_share', float('nan'))*100:5.1f}% "
                f"thrust∩harsh={a.get('thrust_x_harsh_dd_share', float('nan'))*100:5.1f}% "
                f"dcb={a.get('dead_cat_share', float('nan'))*100:5.1f}% "
                f"fwd10_thrust∩harsh={_pp(a.get('mean_fwd10_on_thrust_harsh'))}"
            )
        lines_en.append("")

    m = decision["metrics"]
    lines_en += [
        "## Ablation deltas (maxDD improve = less negative)",
        f"no_thrust_over_harsh vs baseline: {_fpp(m['improve_maxdd_no_thrust_over_harsh_pp'])}",
        f"thrust_demoted vs baseline:       {_fpp(m['improve_maxdd_thrust_demoted_pp'])}",
        f"baseline maxDD vs SPY maxDD:      {_fpp(m['baseline_vs_spy_maxdd_pp'])}",
        f"mean fwd10 on thrust∩harsh:       {_pp(m['mean_fwd10_on_thrust_harsh'])}",
        "",
        "=== END ===",
    ]
    (OUT / "report.txt").write_text("\n".join(lines_en) + "\n")

    lines_zh = [
        "=== V13 實驗 1：2022 全年熊市外推壓力測試（SPY50/QQQ50）===",
        f"資料：Yahoo {YF_START}→{YF_END}，symbols_ok={n_symbols}",
        "設定：$50k｜SPY50/QQQ50｜Futu+3bps｜次日 open｜相對 v13 調參窗為 OOS",
        "",
        f"判決：{decision['verdict']}",
    ]
    for r in decision["reasons"]:
        lines_zh.append(f"  - {r}")
    lines_zh += [
        "",
        f"基準：SPY B&H {_pp(spy['total_return'])}／maxDD {_pp(spy['max_drawdown'])}｜"
        f"靜態 50/50 {_pp(static['total_return'])}／maxDD {_pp(static['max_drawdown'])}",
        "",
        "變體總覽：",
    ]
    labels_zh = {
        "v13_baseline": "v13 生產預設",
        "no_thrust_over_harsh": "關閉 thrust 蓋過 harsh_dd",
        "no_thrust_force": "關閉 thrust 強制 bench",
        "thrust_demoted": "thrust 全面降級",
    }
    for label, rep in results.items():
        b = rep["blend"]
        lines_zh.append(
            f"· {labels_zh.get(label, label)}：報酬 {_pp(b['total_return'])}｜"
            f"maxDD {_pp(b['max_drawdown'])}｜vsSPY {_fpp(b['vs_spy_bh_pp'])}｜"
            f"vs靜態 {_fpp(b['vs_static_etf_blend_pp'])}"
        )
        for s in rep["sleeves"]:
            a = s["audit"]
            lines_zh.append(
                f"    {s['book']}：thrust鎖 {a.get('thrust_lock_share', float('nan'))*100:.1f}%｜"
                f"thrust∩harsh_dd {a.get('thrust_x_harsh_dd_share', float('nan'))*100:.1f}%｜"
                f"死貓跳日占比 {a.get('dead_cat_share', float('nan'))*100:.1f}%｜"
                f"衝突日後10日基準 {_pp(a.get('mean_fwd10_on_thrust_harsh'))}"
            )

    lines_zh += [
        "",
        "## 創除差異（maxDD 改善＝回撤變淺）",
        f"關閉 thrust 蓋過 harsh_dd：{_fpp(m['improve_maxdd_no_thrust_over_harsh_pp'])}",
        f"thrust 全面降級：{_fpp(m['improve_maxdd_thrust_demoted_pp'])}",
        f"baseline maxDD 相對 SPY maxDD：{_fpp(m['baseline_vs_spy_maxdd_pp'])}",
        f"thrust∩harsh_dd 日後 10 日基準均報酬：{_pp(m['mean_fwd10_on_thrust_harsh'])}",
        "",
        "解讀備註：",
        "1. 死貓跳＝基準仍弱（破 SMA50 或 dd60≤−10%）且出現短反彈（ret5≥3%／ret10≥5%／bounce20≥4%）。",
        "2. thrust∩harsh_dd 日數衡量「thrust > harsh_dd」優先序真正起作用的衝突面。",
        "3. 本實驗不改 production；僅回答優先序是否為 2022 巨額回撤主因。",
        "",
        "=== END ===",
    ]
    (OUT / "report_zhTW.txt").write_text("\n".join(lines_zh) + "\n")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    want = sorted(set(WEIGHTS) | set(book_members("QQQ")) | set(book_members("SPY")))
    print(f"universe symbols={len(want)} (SPY50/QQQ50, no SMH)", flush=True)
    bootstrap_cache(want)
    frames = load_from_cache(want)
    for b in WEIGHTS:
        if b not in frames:
            raise SystemExit(f"missing bench {b} after bootstrap")
        print(
            f"bench {b}: {frames[b].index.min().date()}→{frames[b].index.max().date()} "
            f"n={len(frames[b])}",
            flush=True,
        )

    results: dict[str, dict] = {}
    for label, cfg in variant_configs().items():
        results[label] = run_variant(frames, cfg, label=label)

    decision = judge(results)
    write_reports(results, decision, n_symbols=len(frames))
    print("\n" + (OUT / "report_zhTW.txt").read_text())
    print("wrote", OUT / "summary.json")
    print("VERDICT:", decision["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
