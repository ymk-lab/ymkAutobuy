#!/usr/bin/env python3
"""Experiment 2: v13 2024 Jul–Aug tech rotation / fast-drawdown stress.

Window 2024-06-01 → 2024-10-31, unchanged v13 knobs, SPY50/QQQ50.

Success criteria:
  1) During Jul–Aug stress core, successfully sit in cash or bench
     (cash+bench share >= 70% over 2024-07-10 → 2024-08-15)
  2) Blend alpha vs QQQ B&H >= +5pp over the full window

Usage::

    PYTHONPATH=src:examples python examples/run_structure_gate_v13_exp2_2024_rotation.py
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

OUT = ROOT / "examples" / "data" / "structure_gate_v13_exp2_2024_rotation"
CACHE = ROOT / "examples" / "data" / "structure_gate_v13_exp2_2024_rotation" / "cache_ohlcv"
YF_START = "2023-01-01"
YF_END = "2024-11-15"
MIN_BARS = 220
START = pd.Timestamp("2024-06-01")
END = pd.Timestamp("2024-10-31")
# Jul–Aug stress core (AI/tech air-pocket around late Jul / early Aug 2024)
CORE_START = pd.Timestamp("2024-07-10")
CORE_END = pd.Timestamp("2024-08-15")
ALPHA_VS_QQQ_MIN_PP = 5.0
DEFENSE_SHARE_MIN = 0.70
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


def defense_audit(mode: pd.Series, meta: pd.DataFrame, core_start: pd.Timestamp, core_end: pd.Timestamp) -> dict:
    m = mode.loc[core_start:core_end]
    if m.empty:
        return {
            "n_days": 0,
            "cash_share": 0.0,
            "bench_share": 0.0,
            "defense_share": 0.0,
            "ers_strong_share": 0.0,
            "pass_defense": False,
            "risk_override_pierce_days": 0,
            "stock_crash_override_days": 0,
            "mode_daily": [],
        }
    cash = (m == "cash").mean()
    bench = (m == "bench").mean()
    stock = m.isin(["ers", "strong"]).mean()
    defense = cash + bench
    meta_c = meta.reindex(m.index)
    pierce = 0
    crash = 0
    if "risk_override_pierce" in meta_c.columns:
        pierce = int((meta_c["risk_override_pierce"].fillna(0).astype(float) > 0.5).sum())
    if "stock_crash_override" in meta_c.columns:
        crash = int((meta_c["stock_crash_override"].fillna(0).astype(float) > 0.5).sum())
    daily = [
        {
            "date": str(pd.Timestamp(dt).date()),
            "mode": str(m.loc[dt]),
        }
        for dt in m.index
    ]
    return {
        "n_days": int(len(m)),
        "cash_share": float(cash),
        "bench_share": float(bench),
        "defense_share": float(defense),
        "ers_strong_share": float(stock),
        "pass_defense": float(defense) >= DEFENSE_SHARE_MIN,
        "risk_override_pierce_days": pierce,
        "stock_crash_override_days": crash,
        "mode_daily": daily,
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
    if frames["QQQ"].index.max() < END:
        raise SystemExit(f"QQQ history ends {frames['QQQ'].index.max().date()} < {END.date()}")

    cfg = StructureGateConfig.v13()
    book_sims = {}
    sleeves = []
    defense = {}

    print(f"\n=== v13 EXP2 {START.date()}→{END.date()} weights={WEIGHTS} ===", flush=True)
    for book, w in WEIGHTS.items():
        sleeve_cap = CAPITAL * w
        sim, bh, n_mem = run_book(
            book, frames, sleeve_capital=sleeve_cap, start=START, end=END, cfg=cfg
        )
        book_sims[book] = sim
        m = metrics(sim.equity, sleeve_cap)
        mb = metrics(bh, sleeve_cap)
        modes = sim.mode.value_counts(normalize=True).to_dict()
        aud = defense_audit(sim.mode, sim.meta, CORE_START, CORE_END)
        defense[book] = aud
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
            "core_defense": {
                "defense_share": aud["defense_share"],
                "cash_share": aud["cash_share"],
                "bench_share": aud["bench_share"],
                "ers_strong_share": aud["ers_strong_share"],
                "pass_defense": aud["pass_defense"],
                "risk_override_pierce_days": aud["risk_override_pierce_days"],
                "stock_crash_override_days": aud["stock_crash_override_days"],
            },
        }
        sleeves.append(row)
        print(
            f"  {book:4} SG={m['total_return']*100:7.2f}% BH={mb['total_return']*100:6.2f}% "
            f"maxDD={m['max_drawdown']*100:6.2f}% trades={row['n_trades']} "
            f"core defense={aud['defense_share']*100:.0f}% "
            f"(cash {aud['cash_share']*100:.0f}/bench {aud['bench_share']*100:.0f}) "
            f"pierce={aud['risk_override_pierce_days']} crash8%={aud['stock_crash_override_days']}",
            flush=True,
        )
        sim.equity.to_csv(OUT / f"equity_v13_{book}_{START.date()}_{END.date()}.csv", header=["equity"])
        (OUT / f"core_modes_{book}.json").write_text(json.dumps(aud, indent=2, default=float) + "\n")

    blended, _ = blend_structure_gate_books(book_sims, WEIGHTS, capital=CAPITAL)
    blended = blended.loc[START:END].dropna()
    m_b = metrics(blended, CAPITAL)

    from qresearch.backtest.futu_costs import FutuUsEquityFees
    from qresearch.strategy.regime_playbook import simulate_bench_bh

    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    spy = frames["SPY"]
    qqq = frames["QQQ"]
    eq_spy = (
        simulate_bench_bh(spy["open"], spy["close"], capital=CAPITAL, start=START, fees=fees)
        .reindex(blended.index)
        .ffill()
    )
    eq_qqq = (
        simulate_bench_bh(qqq["open"], qqq["close"], capital=CAPITAL, start=START, fees=fees)
        .reindex(blended.index)
        .ffill()
    )
    m_spy = metrics(eq_spy, CAPITAL)
    m_qqq = metrics(eq_qqq, CAPITAL)
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

    alpha_vs_qqq_pp = (m_b["total_return"] - m_qqq["total_return"]) * 100
    # Portfolio defense: both sleeves must pass (or weighted — require each book)
    pass_defense = all(defense[b]["pass_defense"] for b in WEIGHTS)
    pass_alpha = alpha_vs_qqq_pp >= ALPHA_VS_QQQ_MIN_PP
    overall_pass = pass_defense and pass_alpha

    # Blend-level core mode: capital-weighted defense share
    # approximate via average of sleeve defense shares
    blend_defense_share = sum(defense[b]["defense_share"] * WEIGHTS[b] for b in WEIGHTS)

    report = {
        "experiment": "exp2_2024_tech_rotation",
        "preset": "StructureGateConfig.v13",
        "window": [str(START.date()), str(END.date())],
        "core_window": [str(CORE_START.date()), str(CORE_END.date())],
        "capital": CAPITAL,
        "weights": WEIGHTS,
        "criteria": {
            "core_defense_share_min": DEFENSE_SHARE_MIN,
            "alpha_vs_qqq_min_pp": ALPHA_VS_QQQ_MIN_PP,
        },
        "blend": {
            "total_return": m_b["total_return"],
            "max_drawdown": m_b["max_drawdown"],
            "sharpe": m_b["sharpe"],
            "vs_spy_bh_pp": (m_b["total_return"] - m_spy["total_return"]) * 100,
            "vs_qqq_bh_pp": alpha_vs_qqq_pp,
            "vs_static_etf_blend_pp": (m_b["total_return"] - m_static["total_return"]) * 100,
            "n_trades": int(sum(s["n_trades"] for s in sleeves)),
            "core_defense_share_avg": blend_defense_share,
        },
        "spy_bh": {"total_return": m_spy["total_return"], "max_drawdown": m_spy["max_drawdown"]},
        "qqq_bh": {"total_return": m_qqq["total_return"], "max_drawdown": m_qqq["max_drawdown"]},
        "static_etf": {
            "total_return": m_static["total_return"],
            "max_drawdown": m_static["max_drawdown"],
        },
        "sleeves": sleeves,
        "verdict": {
            "pass_defense_cash_or_bench": pass_defense,
            "pass_alpha_vs_qqq": pass_alpha,
            "overall_pass": overall_pass,
        },
        "data": {
            "cache": str(CACHE),
            "n_symbols": len(frames),
            "yf_start": YF_START,
            "yf_end": YF_END,
        },
        "note": (
            "OOS vs v13 tune. Defense = cash+bench share in Jul10–Aug15 core. "
            "Alpha = blend total return − QQQ B&H over full window."
        ),
    }
    out_json = OUT / f"exp2_{START.date()}_{END.date()}.json"
    out_json.write_text(json.dumps(report, indent=2, default=float) + "\n")

    lines = [
        "=== 實驗 2：v13 2024 科技輪動 / 快速回撤壓力測 ===",
        f"窗：{START.date()} → {END.date()}｜核心壓力：{CORE_START.date()} → {CORE_END.date()}",
        f"資本 ${CAPITAL:,.0f}｜權重 SPY50/QQQ50｜參數不變 v13",
        f"資料：Yahoo {YF_START}→{YF_END}｜symbols_ok={len(frames)}",
        "",
        f"Blend：ret {m_b['total_return']*100:+.2f}%｜maxDD {m_b['max_drawdown']*100:.2f}%｜"
        f"Sharpe {m_b['sharpe']:.2f}｜trades {report['blend']['n_trades']}",
        f"QQQ B&H：{m_qqq['total_return']*100:+.2f}%｜SPY B&H：{m_spy['total_return']*100:+.2f}%｜"
        f"靜態 SPY50/QQQ50：{m_static['total_return']*100:+.2f}%",
        f"vsQQQ {alpha_vs_qqq_pp:+.1f}pp｜vsSPY {report['blend']['vs_spy_bh_pp']:+.1f}pp｜"
        f"vsStatic {report['blend']['vs_static_etf_blend_pp']:+.1f}pp",
        "",
        "袖口：",
    ]
    for s in sleeves:
        cd = s["core_defense"]
        lines.append(
            f"  {s['book']}: {s['total_return']*100:+.2f}%｜maxDD {s['max_drawdown']*100:.2f}%｜"
            f"trades {s['n_trades']}｜核心 defense {cd['defense_share']*100:.0f}% "
            f"(cash {cd['cash_share']*100:.0f}/bench {cd['bench_share']*100:.0f}/"
            f"ers+strong {cd['ers_strong_share']*100:.0f})｜"
            f"pierce {cd['risk_override_pierce_days']}｜crash8% {cd['stock_crash_override_days']}"
        )
    lines += [
        "",
        "判準：",
        f"  1) 核心期成功坐 cash/bench（≥{DEFENSE_SHARE_MIN*100:.0f}%）："
        f"{'PASS' if pass_defense else 'FAIL'} "
        f"(加權 defense {blend_defense_share*100:.0f}%)",
        f"  2) vs QQQ alpha ≥ +{ALPHA_VS_QQQ_MIN_PP:.0f}pp："
        f"{'PASS' if pass_alpha else 'FAIL'} (實際 {alpha_vs_qqq_pp:+.1f}pp)",
        f"總判決：{'PASS' if overall_pass else 'FAIL'}",
        "",
        "預期失效模式：遲滯 3.5%/−1.5% 頂部鎖利太慢；底部冷靜期無法及時回補。",
        "註：相對 v13 調參窗為 OOS。",
    ]
    txt = "\n".join(lines) + "\n"
    (OUT / f"exp2_{START.date()}_{END.date()}_zhTW.txt").write_text(txt, encoding="utf-8")
    print("\n" + txt)
    print(f"wrote {out_json}")
    return 0 if overall_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
