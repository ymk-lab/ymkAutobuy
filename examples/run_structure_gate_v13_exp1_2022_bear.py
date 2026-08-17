#!/usr/bin/env python3
"""Experiment 1: v13 2022 full-year bear-market OOS stress (SPY50/QQQ50).

Success criteria (from AI verify prompt):
  1) Max Drawdown < 22%
  2) No streak of >=2 consecutive thrust triggers that are harsh-stopped
     within 5 trading days

Usage::

    PYTHONPATH=src:examples python examples/run_structure_gate_v13_exp1_2022_bear.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

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

OUT = ROOT / "examples" / "data" / "structure_gate_v13_exp1_2022_bear"
CACHE = ROOT / "examples" / "data" / "structure_gate_v13_vs_v11" / "cache_ohlcv_2019"
YF_START = "2019-01-01"
YF_END = "2023-06-01"
MIN_BARS = 220
START = pd.Timestamp("2022-01-01")
END = pd.Timestamp("2022-12-31")
MAX_DD_PASS = -0.22  # success if maxDD > -22% i.e. shallower than 22%
HARSH_WINDOW = 5
WEIGHTS = dict(V13_BOOK_WEIGHTS)


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
    print(f"cache={CACHE} present={len(symbols)-len(missing)} missing={len(missing)}", flush=True)
    if not missing:
        return

    chunk = 40
    for i in range(0, len(missing), chunk):
        batch = missing[i : i + chunk]
        print(f"yf batch {i+1}-{i+len(batch)} / {len(missing)}: {batch[:5]}…", flush=True)
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
            df = None
            if raw is not None and len(batch) > 1:
                try:
                    if isinstance(raw.columns, pd.MultiIndex) and sym in raw.columns.get_level_values(0):
                        df = _normalize_yf(raw[sym].dropna(how="all"))
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


def thrust_harsh_failures(meta: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """Detect thrust rising-edge → harsh within N days; measure consecutive streaks.

    A failure event: thrust_lock rises (0→1), then within HARSH_WINDOW sessions
    either harsh_ret or harsh_dd is true (defense punch after dead-cat thrust).
    """
    m = meta.loc[start:end].copy()
    if m.empty:
        return {
            "n_thrust_triggers": 0,
            "n_failures": 0,
            "max_consecutive_failures": 0,
            "events": [],
            "pass_no_double_streak": True,
        }

    thrust = m.get("thrust", pd.Series(0.0, index=m.index)).fillna(0.0).astype(float) > 0.5
    harsh = (
        (m.get("harsh_ret", pd.Series(0.0, index=m.index)).fillna(0.0).astype(float) > 0.5)
        | (m.get("harsh_dd", pd.Series(0.0, index=m.index)).fillna(0.0).astype(float) > 0.5)
    )
    mode = m.get("mode", pd.Series(index=m.index, dtype=object))

    # rising edge of thrust lock
    prev = thrust.shift(1).fillna(False)
    triggers = thrust & ~prev
    trigger_dates = list(m.index[triggers])

    events = []
    for dt in trigger_dates:
        loc = m.index.get_loc(dt)
        if isinstance(loc, slice):
            continue
        i = int(loc)
        window = m.index[i : i + 1 + HARSH_WINDOW]
        h_hit = harsh.reindex(window).fillna(False)
        hit_days = list(window[h_hit.to_numpy()])
        failed = len(hit_days) > 0
        # also note if mode went cash in window after thrust
        modes = mode.reindex(window).astype(str).tolist()
        events.append(
            {
                "thrust_date": str(pd.Timestamp(dt).date()),
                "failed": failed,
                "harsh_hit_dates": [str(pd.Timestamp(x).date()) for x in hit_days],
                "modes_in_window": modes,
            }
        )

    # consecutive failure streak among trigger events (in time order)
    max_streak = 0
    cur = 0
    for ev in events:
        if ev["failed"]:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0

    return {
        "n_thrust_triggers": len(events),
        "n_failures": int(sum(1 for e in events if e["failed"])),
        "max_consecutive_failures": int(max_streak),
        "events": events,
        "pass_no_double_streak": max_streak < 2,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    want = sorted(set(WEIGHTS) | {m for b in WEIGHTS for m in book_members(b)})
    bootstrap_cache(want)
    frames = load_from_cache(want)
    for b in WEIGHTS:
        if b not in frames:
            raise SystemExit(f"missing bench {b}")
        print(
            f"bench {b}: {frames[b].index.min().date()}→{frames[b].index.max().date()} "
            f"n={len(frames[b])}",
            flush=True,
        )

    cfg = StructureGateConfig.v13()
    book_sims = {}
    sleeves = []
    thrust_audit = {}

    print(f"\n=== v13 EXP1 {START.date()}→{END.date()} weights={WEIGHTS} ===", flush=True)
    for book, w in WEIGHTS.items():
        sleeve_cap = CAPITAL * w
        sim, bh, n_mem = run_book(
            book, frames, sleeve_capital=sleeve_cap, start=START, end=END, cfg=cfg
        )
        book_sims[book] = sim
        m = metrics(sim.equity, sleeve_cap)
        mb = metrics(bh, sleeve_cap)
        modes = sim.mode.value_counts(normalize=True).to_dict()
        audit = thrust_harsh_failures(sim.meta, START, END)
        thrust_audit[book] = audit
        row = {
            "book": book,
            "weight": w,
            "n_members": n_mem,
            "total_return": m["total_return"],
            "max_drawdown": m["max_drawdown"],
            "sharpe": m["sharpe"],
            "bh_total_return": mb["total_return"],
            "mode_distribution": modes,
            "n_trades": int(len(sim.trades)),
            "thrust_harsh": {
                "n_thrust_triggers": audit["n_thrust_triggers"],
                "n_failures": audit["n_failures"],
                "max_consecutive_failures": audit["max_consecutive_failures"],
                "pass_no_double_streak": audit["pass_no_double_streak"],
            },
        }
        sleeves.append(row)
        print(
            f"  {book:4} SG={m['total_return']*100:7.2f}% BH={mb['total_return']*100:6.2f}% "
            f"maxDD={m['max_drawdown']*100:6.2f}% trades={row['n_trades']} "
            f"thrust→harsh fail={audit['n_failures']}/{audit['n_thrust_triggers']} "
            f"maxStreak={audit['max_consecutive_failures']}",
            flush=True,
        )
        sim.equity.to_csv(OUT / f"equity_v13_{book}_{START.date()}_{END.date()}.csv", header=["equity"])
        # keep event detail
        (OUT / f"thrust_harsh_{book}.json").write_text(
            json.dumps(audit, indent=2, default=float) + "\n"
        )

    blended, _ = blend_structure_gate_books(book_sims, WEIGHTS, capital=CAPITAL)
    blended = blended.loc[START:END].dropna()
    m_b = metrics(blended, CAPITAL)

    from qresearch.backtest.futu_costs import FutuUsEquityFees
    from qresearch.strategy.regime_playbook import simulate_bench_bh

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
    blended.to_csv(OUT / f"equity_v13_blend_{START.date()}_{END.date()}.csv", header=["equity"])

    # Portfolio-level thrust criterion: fail if ANY sleeve has streak >= 2
    sleeve_streaks = [thrust_audit[b]["max_consecutive_failures"] for b in WEIGHTS]
    max_streak_any = max(sleeve_streaks) if sleeve_streaks else 0
    pass_dd = float(m_b["max_drawdown"]) > MAX_DD_PASS  # e.g. -0.18 > -0.22
    pass_thrust = max_streak_any < 2
    overall_pass = pass_dd and pass_thrust

    report = {
        "experiment": "exp1_2022_bear_oos",
        "preset": "StructureGateConfig.v13",
        "window": [str(START.date()), str(END.date())],
        "capital": CAPITAL,
        "weights": WEIGHTS,
        "criteria": {
            "max_drawdown_shallower_than": MAX_DD_PASS,
            "thrust_harsh_window_days": HARSH_WINDOW,
            "max_consecutive_thrust_harsh_failures_allowed": 1,
        },
        "blend": {
            "total_return": m_b["total_return"],
            "max_drawdown": m_b["max_drawdown"],
            "sharpe": m_b["sharpe"],
            "vs_spy_bh_pp": (m_b["total_return"] - m_bh["total_return"]) * 100,
            "vs_static_etf_blend_pp": (m_b["total_return"] - m_static["total_return"]) * 100,
            "n_trades": int(sum(s["n_trades"] for s in sleeves)),
        },
        "spy_bh": {
            "total_return": m_bh["total_return"],
            "max_drawdown": m_bh["max_drawdown"],
        },
        "static_etf": {
            "total_return": m_static["total_return"],
            "max_drawdown": m_static["max_drawdown"],
        },
        "sleeves": sleeves,
        "thrust_harsh_portfolio": {
            "max_consecutive_failures_any_sleeve": max_streak_any,
            "pass_no_double_streak": pass_thrust,
        },
        "verdict": {
            "pass_maxdd": pass_dd,
            "pass_thrust_harsh": pass_thrust,
            "overall_pass": overall_pass,
        },
        "data": {
            "cache": str(CACHE),
            "n_symbols": len(frames),
            "yf_start": YF_START,
            "yf_end": YF_END,
        },
        "note": (
            "OOS vs v13 tune windows (2023, 2025). "
            "Thrust failure = thrust_lock rising edge then harsh_ret|harsh_dd within 5 sessions."
        ),
    }
    out_json = OUT / f"exp1_{START.date()}_{END.date()}.json"
    out_json.write_text(json.dumps(report, indent=2, default=float) + "\n")

    lines = [
        "=== 實驗 1：v13 2022 全年熊市外推 ===",
        f"窗：{START.date()} → {END.date()}｜資本 ${CAPITAL:,.0f}｜權重 SPY50/QQQ50｜參數不變 v13",
        f"資料：Yahoo {YF_START}→{YF_END}｜symbols_ok={len(frames)}",
        "",
        f"Blend：ret {m_b['total_return']*100:+.2f}%｜maxDD {m_b['max_drawdown']*100:.2f}%｜"
        f"Sharpe {m_b['sharpe']:.2f}｜trades {report['blend']['n_trades']}",
        f"SPY B&H：{m_bh['total_return']*100:+.2f}%｜靜態 SPY50/QQQ50：{m_static['total_return']*100:+.2f}%",
        f"vsSPY {report['blend']['vs_spy_bh_pp']:+.1f}pp｜vsStatic {report['blend']['vs_static_etf_blend_pp']:+.1f}pp",
        "",
        "袖口：",
    ]
    for s in sleeves:
        th = s["thrust_harsh"]
        lines.append(
            f"  {s['book']}: {s['total_return']*100:+.2f}%｜maxDD {s['max_drawdown']*100:.2f}%｜"
            f"trades {s['n_trades']}｜thrust→harsh {th['n_failures']}/{th['n_thrust_triggers']} "
            f"(max連擊 {th['max_consecutive_failures']})"
        )
    lines += [
        "",
        "判準：",
        f"  1) MaxDD < 22%：{'PASS' if pass_dd else 'FAIL'} "
        f"(實際 {m_b['max_drawdown']*100:.2f}%)",
        f"  2) 無連續≥2次 thrust→5日內harsh：{'PASS' if pass_thrust else 'FAIL'} "
        f"(最大連擊 {max_streak_any})",
        f"總判決：{'PASS' if overall_pass else 'FAIL'}",
        "",
        "預期失效模式：Thrust 抄底後被主跌浪 harsh 打出。",
        "註：相對 v13 調參窗（2023/2025）為 OOS。",
    ]
    txt = "\n".join(lines) + "\n"
    (OUT / f"exp1_{START.date()}_{END.date()}_zhTW.txt").write_text(txt, encoding="utf-8")
    print("\n" + txt)
    print(f"wrote {out_json}")
    return 0 if overall_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
