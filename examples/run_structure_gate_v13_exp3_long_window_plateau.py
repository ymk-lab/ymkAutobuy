#!/usr/bin/env python3
"""Experiment 3: long-window robustness plateau (55/58/60/62/65).

Goal: show sticky/strong/ers_lag lookback=60 is not an isolated peak hazard.
Window: 2021-01-01 → latest available through 2026-08.
Base knobs: StructureGateConfig.v13(); only long windows vary.

Success:
  - CV of annualized return across the 5 settings < 15%
  - CV of Sharpe across the 5 settings < 15%
  - No cliff vs 60d baseline (any setting Δret ≤ −20pp fails)

Usage::

    PYTHONPATH=src:examples python examples/run_structure_gate_v13_exp3_long_window_plateau.py
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

from qresearch.data.loader import validate_ohlcv  # noqa: E402
from qresearch.strategy.structure_gate import (  # noqa: E402
    V13_BOOK_WEIGHTS,
    StructureGateConfig,
    blend_structure_gate_books,
)
from run_emerging_rs_wave_gates import metrics  # type: ignore  # noqa: E402
from run_structure_gate_v13_blend import (  # type: ignore  # noqa: E402
    CAPITAL,
    book_members,
    run_book,
)

OUT = ROOT / "examples" / "data" / "structure_gate_v13_exp3_long_window_plateau"
CACHE = OUT / "cache_ohlcv"
SEED_CACHES = [
    ROOT / "examples/data/structure_gate_v13_vs_v11/cache_ohlcv_2019",
    ROOT / "examples/data/structure_gate_v13_exp2_2024_rotation/cache_ohlcv",
]
YF_START = "2020-01-01"
YF_END = "2026-08-16"
MIN_BARS = 220
START = pd.Timestamp("2021-01-01")
END = pd.Timestamp("2026-08-13")
LONG_WINDOWS = [55, 58, 60, 62, 65]
CV_MAX = 0.15
CLIFF_PP = -20.0  # fail if any setting is ≤ baseline60 by this many pp
WEIGHTS = dict(V13_BOOK_WEIGHTS)


def _normalize_yf(raw: pd.DataFrame) -> pd.DataFrame | None:
    if raw is None or len(raw) < 30:
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
    try:
        df = validate_ohlcv(raw[need].dropna())
    except Exception:
        return None
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[~df.index.duplicated(keep="last")].sort_index()


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    try:
        raw = pd.read_csv(path, index_col=0, parse_dates=True)
        raw.columns = [str(c).lower() for c in raw.columns]
        df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        return df[~df.index.duplicated(keep="last")].sort_index()
    except Exception:
        return None


def seed_cache_from_existing(symbols: list[str]) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    n_write = 0
    for sym in symbols:
        out = CACHE / f"{sym}.csv"
        if out.is_file():
            continue
        parts = []
        for seed in SEED_CACHES:
            df = _read_csv(seed / f"{sym}.csv")
            if df is not None and len(df):
                parts.append(df)
        if not parts:
            continue
        merged = pd.concat(parts).sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]
        if len(merged) >= MIN_BARS:
            merged.to_csv(out)
            n_write += 1
    print(f"seeded {n_write} symbols into {CACHE} from existing caches", flush=True)


def extend_cache_via_yahoo(symbols: list[str]) -> None:
    """Fill gaps / extend to YF_END for symbols that end before END."""
    import yfinance as yf

    need_ext = []
    for sym in symbols:
        path = CACHE / f"{sym}.csv"
        df = _read_csv(path)
        if df is None or len(df) < MIN_BARS or df.index.max() < END - pd.Timedelta(days=5):
            need_ext.append(sym)
    print(f"yahoo extend candidates={len(need_ext)}", flush=True)
    if not need_ext:
        return

    chunk = 40
    for i in range(0, len(need_ext), chunk):
        batch = need_ext[i : i + chunk]
        print(f"yf batch {i+1}-{i+len(batch)} / {len(need_ext)}: {batch[:5]}…", flush=True)
        raw = None
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

        for sym in batch:
            path = CACHE / f"{sym}.csv"
            existing = _read_csv(path)
            fresh = None
            if raw is not None and len(batch) > 1:
                try:
                    if isinstance(raw.columns, pd.MultiIndex) and sym in raw.columns.get_level_values(0):
                        fresh = _normalize_yf(raw[sym].dropna(how="all"))
                except Exception:
                    fresh = None
            elif raw is not None and len(batch) == 1:
                fresh = _normalize_yf(raw)
            if fresh is None:
                try:
                    one = yf.download(
                        sym,
                        start=YF_START,
                        end=YF_END,
                        auto_adjust=True,
                        progress=False,
                        threads=False,
                    )
                    fresh = _normalize_yf(one)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {sym} fail: {exc}", flush=True)
                    continue
            parts = [p for p in (existing, fresh) if p is not None and len(p)]
            if not parts:
                continue
            merged = pd.concat(parts).sort_index()
            merged = merged[~merged.index.duplicated(keep="last")]
            if len(merged) >= MIN_BARS:
                merged.to_csv(path)
            else:
                print(f"  {sym} skip bars={len(merged)}", flush=True)
        time.sleep(0.3)


def load_from_cache(symbols: list[str]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols, 1):
        df = _read_csv(CACHE / f"{sym}.csv")
        if df is not None and len(df) >= MIN_BARS:
            frames[sym] = df
        if i == 1 or i % 80 == 0 or i == len(symbols):
            print(f"load [{i}/{len(symbols)}] ok={len(frames)}", flush=True)
    return frames


def cfg_for_long(n: int) -> StructureGateConfig:
    return replace(
        StructureGateConfig.v13(),
        sticky_trail_days=n,
        strong_lookback=n,
        ers_lag_lookback=n,
    )


def annualize(total_return: float, start: pd.Timestamp, end: pd.Timestamp) -> float:
    years = max((end - start).days / 365.25, 1e-9)
    if total_return <= -0.999999:
        return -1.0
    return float((1.0 + total_return) ** (1.0 / years) - 1.0)


def cv(vals: list[float]) -> float:
    arr = np.asarray(vals, dtype=float)
    mu = float(arr.mean())
    sd = float(arr.std(ddof=0))
    if abs(mu) < 1e-12:
        return float("inf") if sd > 1e-12 else 0.0
    return float(sd / abs(mu))


def run_preset(label: str, cfg: StructureGateConfig, frames: dict, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    book_sims = {}
    sleeves = []
    print(f"\n=== {label} long={cfg.sticky_trail_days} {start.date()}→{end.date()} ===", flush=True)
    for book, w in WEIGHTS.items():
        sleeve_cap = CAPITAL * w
        sim, bh, n_mem = run_book(
            book, frames, sleeve_capital=sleeve_cap, start=start, end=end, cfg=cfg
        )
        book_sims[book] = sim
        m = metrics(sim.equity, sleeve_cap)
        sleeves.append(
            {
                "book": book,
                "weight": w,
                "n_members": n_mem,
                "total_return": m["total_return"],
                "max_drawdown": m["max_drawdown"],
                "sharpe": m["sharpe"],
                "n_trades": int(len(sim.trades)),
            }
        )
        print(
            f"  {book:4} SG={m['total_return']*100:7.2f}% maxDD={m['max_drawdown']*100:6.2f}% "
            f"sharpe={m['sharpe']:.2f} trades={len(sim.trades)}",
            flush=True,
        )

    blended, _ = blend_structure_gate_books(book_sims, WEIGHTS, capital=CAPITAL)
    blended = blended.loc[start:end].dropna()
    m_b = metrics(blended, CAPITAL)
    ann = annualize(m_b["total_return"], blended.index[0], blended.index[-1])
    out = {
        "label": label,
        "long_window": cfg.sticky_trail_days,
        "total_return": m_b["total_return"],
        "ann_return": ann,
        "max_drawdown": m_b["max_drawdown"],
        "sharpe": m_b["sharpe"],
        "n_trades": int(sum(s["n_trades"] for s in sleeves)),
        "sleeves": sleeves,
    }
    print(
        f"  BLEND ret={m_b['total_return']*100:+.2f}% ann={ann*100:+.2f}% "
        f"sharpe={m_b['sharpe']:.2f} maxDD={m_b['max_drawdown']*100:.2f}%",
        flush=True,
    )
    blended.to_csv(OUT / f"equity_{label}_{start.date()}_{end.date()}.csv", header=["equity"])
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    want = sorted(set(WEIGHTS) | {m for b in WEIGHTS for m in book_members(b)})
    seed_cache_from_existing(want)
    extend_cache_via_yahoo(want)
    frames = load_from_cache(want)
    for b in WEIGHTS:
        if b not in frames:
            raise SystemExit(f"missing bench {b}")
        print(
            f"bench {b}: {frames[b].index.min().date()}→{frames[b].index.max().date()} "
            f"n={len(frames[b])}",
            flush=True,
        )

    # clip END to available data
    end = min(END, frames["SPY"].index.max(), frames["QQQ"].index.max())
    if end < pd.Timestamp("2025-01-01"):
        raise SystemExit(f"history too short for 2021–2026 test; end={end.date()}")
    start = START
    print(f"effective window {start.date()}→{end.date()}", flush=True)

    rows = []
    for n in LONG_WINDOWS:
        label = f"L{n}"
        rows.append(run_preset(label, cfg_for_long(n), frames, start, end))

    ann_vals = [r["ann_return"] for r in rows]
    sharpe_vals = [r["sharpe"] for r in rows]
    cv_ann = cv(ann_vals)
    cv_sharpe = cv(sharpe_vals)
    base = next(r for r in rows if r["long_window"] == 60)
    deltas = []
    cliff = False
    for r in rows:
        d_pp = (r["total_return"] - base["total_return"]) * 100
        deltas.append({"long_window": r["long_window"], "delta_ret_pp_vs_60": d_pp})
        if r["long_window"] != 60 and d_pp <= CLIFF_PP:
            cliff = True

    pass_cv_ann = cv_ann < CV_MAX
    pass_cv_sharpe = cv_sharpe < CV_MAX
    pass_no_cliff = not cliff
    overall = pass_cv_ann and pass_cv_sharpe and pass_no_cliff

    report = {
        "experiment": "exp3_long_window_plateau",
        "preset_base": "StructureGateConfig.v13",
        "window": [str(start.date()), str(end.date())],
        "capital": CAPITAL,
        "weights": WEIGHTS,
        "long_windows": LONG_WINDOWS,
        "criteria": {
            "cv_ann_max": CV_MAX,
            "cv_sharpe_max": CV_MAX,
            "cliff_delta_ret_pp_vs_60": CLIFF_PP,
        },
        "rows": rows,
        "stats": {
            "ann_returns": ann_vals,
            "sharpes": sharpe_vals,
            "cv_ann": cv_ann,
            "cv_sharpe": cv_sharpe,
            "deltas_vs_60": deltas,
        },
        "verdict": {
            "pass_cv_ann": pass_cv_ann,
            "pass_cv_sharpe": pass_cv_sharpe,
            "pass_no_cliff": pass_no_cliff,
            "overall_pass": overall,
        },
        "data": {"cache": str(CACHE), "n_symbols": len(frames)},
        "note": (
            "Only sticky_trail_days/strong_lookback/ers_lag_lookback vary; "
            "all other knobs frozen at v13. CV = std/|mean| across the 5 settings."
        ),
    }
    out_json = OUT / f"exp3_{start.date()}_{end.date()}.json"
    out_json.write_text(json.dumps(report, indent=2, default=float) + "\n")

    lines = [
        "=== 實驗 3：長窗敏感度微擾平滑（Robustness Plateaus）===",
        f"窗：{start.date()} → {end.date()}｜資本 ${CAPITAL:,.0f}｜權重 SPY50/QQQ50｜v13 其餘 knobs 凍結",
        f"長窗網格：{LONG_WINDOWS}",
        f"資料 symbols_ok={len(frames)}",
        "",
        "結果：",
    ]
    for r in rows:
        d = next(x["delta_ret_pp_vs_60"] for x in deltas if x["long_window"] == r["long_window"])
        lines.append(
            f"  L{r['long_window']}: ret {r['total_return']*100:+.2f}%｜ann {r['ann_return']*100:+.2f}%｜"
            f"Sharpe {r['sharpe']:.2f}｜maxDD {r['max_drawdown']*100:.2f}%｜"
            f"trades {r['n_trades']}｜Δvs60 {d:+.2f}pp"
        )
    lines += [
        "",
        f"CV(ann) = {cv_ann*100:.2f}%｜CV(Sharpe) = {cv_sharpe*100:.2f}%",
        "",
        "判準：",
        f"  1) CV(ann) < 15%：{'PASS' if pass_cv_ann else 'FAIL'} ({cv_ann*100:.2f}%)",
        f"  2) CV(Sharpe) < 15%：{'PASS' if pass_cv_sharpe else 'FAIL'} ({cv_sharpe*100:.2f}%)",
        f"  3) 無相對 L60 斷崖（≤{CLIFF_PP:.0f}pp）：{'PASS' if pass_no_cliff else 'FAIL'}",
        f"總判決：{'PASS' if overall else 'FAIL'}",
        "",
        "預期失效模式：報酬曲線階梯斷裂 → 60 日為噪音尖峰。",
        "註：相對「只在 60」的尖峰假設；本實驗為平滑微擾，不含 v15 的 50 日遠端跳點。",
    ]
    txt = "\n".join(lines) + "\n"
    (OUT / f"exp3_{start.date()}_{end.date()}_zhTW.txt").write_text(txt, encoding="utf-8")
    print("\n" + txt)
    print(f"wrote {out_json}")
    return 0 if overall else 2


if __name__ == "__main__":
    raise SystemExit(main())
