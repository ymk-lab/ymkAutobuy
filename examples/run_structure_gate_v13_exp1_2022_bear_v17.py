#!/usr/bin/env python3
"""Re-run Experiment 1 (2022 bear) for v13 vs v17 grinding-bear fix.

v17: harsh_defense_dd 0.20→0.10 + harsh_dd pierces sticky (thrust override kept).

Usage::

    PYTHONPATH=src:examples python examples/run_structure_gate_v13_exp1_2022_bear_v17.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.backtest.futu_costs import FutuUsEquityFees  # noqa: E402
from qresearch.data.loader import validate_ohlcv  # noqa: E402
from qresearch.strategy.regime_playbook import simulate_bench_bh  # noqa: E402
from qresearch.strategy.structure_gate import (  # noqa: E402
    V13_BOOK_WEIGHTS,
    StructureGateConfig,
    blend_structure_gate_books,
)
from run_emerging_rs_wave_gates import metrics  # type: ignore  # noqa: E402
from run_structure_gate_v13_blend import CAPITAL, book_members, run_book  # type: ignore  # noqa: E402
from run_structure_gate_v13_exp1_2022_bear import thrust_harsh_failures  # type: ignore  # noqa: E402

OUT = ROOT / "examples" / "data" / "structure_gate_v13_exp1_2022_bear_v17"
CACHE = ROOT / "examples" / "data" / "structure_gate_v13_exp3_long_window_plateau" / "cache_ohlcv"
MIN_BARS = 220
START = pd.Timestamp("2022-01-01")
END = pd.Timestamp("2022-12-31")
MAX_DD_PASS = -0.22
WEIGHTS = dict(V13_BOOK_WEIGHTS)


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


def run_variant(label: str, cfg: StructureGateConfig, frames: dict) -> dict:
    book_sims = {}
    sleeves = []
    print(f"\n=== {label} {START.date()}→{END.date()} ===", flush=True)
    for book, w in WEIGHTS.items():
        sleeve_cap = CAPITAL * w
        sim, bh, n_mem = run_book(
            book, frames, sleeve_capital=sleeve_cap, start=START, end=END, cfg=cfg
        )
        book_sims[book] = sim
        m = metrics(sim.equity, sleeve_cap)
        mb = metrics(bh, sleeve_cap)
        mode = sim.mode.loc[START:END]
        meta = sim.meta.loc[START:END]
        audit = thrust_harsh_failures(meta, START, END)
        modes = mode.value_counts(normalize=True).to_dict()
        sticky = float((meta["sticky"].fillna(0) > 0.5).mean()) if "sticky" in meta else 0.0
        harsh_dd = float((meta["harsh_dd"].fillna(0) > 0.5).mean()) if "harsh_dd" in meta else 0.0
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
            "sticky_share": sticky,
            "harsh_dd_share": harsh_dd,
            "thrust_harsh": {
                "n_thrust_triggers": audit["n_thrust_triggers"],
                "n_failures": audit["n_failures"],
                "max_consecutive_failures": audit["max_consecutive_failures"],
                "pass_no_double_streak": audit["pass_no_double_streak"],
            },
        }
        sleeves.append(row)
        print(
            f"  {book:4} SG={m['total_return']*100:7.2f}% maxDD={m['max_drawdown']*100:6.2f}% "
            f"B/C={(modes.get('bench',0)*100):.0f}/{(modes.get('cash',0)*100):.0f} "
            f"sticky={sticky*100:.0f}% harsh_dd={harsh_dd*100:.0f}% "
            f"thrust→harsh {audit['n_failures']}/{audit['n_thrust_triggers']} "
            f"streak={audit['max_consecutive_failures']}",
            flush=True,
        )
        sim.equity.to_csv(OUT / f"equity_{label}_{book}.csv", header=["equity"])

    blended, _ = blend_structure_gate_books(book_sims, WEIGHTS, capital=CAPITAL)
    blended = blended.loc[START:END].dropna()
    m_b = metrics(blended, CAPITAL)
    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    spy = frames["SPY"]
    eq_bh = (
        simulate_bench_bh(spy["open"], spy["close"], capital=CAPITAL, start=START, fees=fees)
        .reindex(blended.index)
        .ffill()
    )
    m_bh = metrics(eq_bh, CAPITAL)
    etf_eq = [
        simulate_bench_bh(
            frames[book]["open"], frames[book]["close"], capital=CAPITAL * w, start=START, fees=fees
        )
        for book, w in WEIGHTS.items()
    ]
    static = pd.concat(etf_eq, axis=1).ffill().sum(axis=1).reindex(blended.index).ffill()
    m_static = metrics(static, CAPITAL)
    blended.to_csv(OUT / f"equity_{label}_blend.csv", header=["equity"])

    max_streak = max(s["thrust_harsh"]["max_consecutive_failures"] for s in sleeves)
    pass_dd = float(m_b["max_drawdown"]) > MAX_DD_PASS
    pass_thrust = max_streak < 2
    return {
        "label": label,
        "cfg": {
            "harsh_defense_dd": cfg.harsh_defense_dd,
            "harsh_dd_pierces_sticky": cfg.harsh_dd_pierces_sticky,
            "thrust_overrides_dd_harsh": cfg.thrust_overrides_dd_harsh,
        },
        "blend": {
            "total_return": m_b["total_return"],
            "max_drawdown": m_b["max_drawdown"],
            "sharpe": m_b["sharpe"],
            "vs_spy_bh_pp": (m_b["total_return"] - m_bh["total_return"]) * 100,
            "vs_static_etf_blend_pp": (m_b["total_return"] - m_static["total_return"]) * 100,
            "n_trades": int(sum(s["n_trades"] for s in sleeves)),
        },
        "spy_bh": {"total_return": m_bh["total_return"]},
        "static_etf": {"total_return": m_static["total_return"]},
        "sleeves": sleeves,
        "verdict": {
            "pass_maxdd": pass_dd,
            "pass_thrust_harsh": pass_thrust,
            "overall_pass": pass_dd and pass_thrust,
            "max_consecutive_thrust_harsh": max_streak,
        },
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    want = sorted(set(WEIGHTS) | {m for b in WEIGHTS for m in book_members(b)})
    frames = load_from_cache(want)
    for b in WEIGHTS:
        if b not in frames:
            raise SystemExit(f"missing {b}")

    v13 = run_variant("v13", StructureGateConfig.v13(), frames)
    v17 = run_variant("v17", StructureGateConfig.v17(), frames)

    report = {
        "experiment": "exp1_2022_bear_rerun_v17",
        "window": [str(START.date()), str(END.date())],
        "capital": CAPITAL,
        "weights": WEIGHTS,
        "criteria": {"max_drawdown_shallower_than": MAX_DD_PASS},
        "v13": v13,
        "v17": v17,
        "delta_v17_minus_v13": {
            "ret_pp": (v17["blend"]["total_return"] - v13["blend"]["total_return"]) * 100,
            "maxdd_pp": (v17["blend"]["max_drawdown"] - v13["blend"]["max_drawdown"]) * 100,
            "spy_cash_pp": (
                v17["sleeves"][0]["mode_distribution"].get("cash", 0)
                - v13["sleeves"][0]["mode_distribution"].get("cash", 0)
            )
            * 100,
            "spy_bench_pp": (
                v17["sleeves"][0]["mode_distribution"].get("bench", 0)
                - v13["sleeves"][0]["mode_distribution"].get("bench", 0)
            )
            * 100,
        },
        "note": (
            "v17 fixes 2022 SPY 陰跌: sticky was pinning bench while harsh_dd≈0. "
            "Only lowering harsh_defense_dd without pierce does almost nothing."
        ),
    }
    out_json = OUT / f"exp1_rerun_{START.date()}_{END.date()}.json"
    out_json.write_text(json.dumps(report, indent=2, default=float) + "\n")

    def line(tag: str, r: dict) -> str:
        b = r["blend"]
        v = r["verdict"]
        spy = r["sleeves"][0]
        return (
            f"{tag}: ret {b['total_return']*100:+.2f}%｜maxDD {b['max_drawdown']*100:.2f}%｜"
            f"trades {b['n_trades']}｜"
            f"SPY B/C {spy['mode_distribution'].get('bench',0)*100:.0f}/"
            f"{spy['mode_distribution'].get('cash',0)*100:.0f}｜"
            f"MaxDD門 {'PASS' if v['pass_maxdd'] else 'FAIL'}｜"
            f"thrust連擊 {'PASS' if v['pass_thrust_harsh'] else 'FAIL'}｜"
            f"總判 {'PASS' if v['overall_pass'] else 'FAIL'}"
        )

    d = report["delta_v17_minus_v13"]
    lines = [
        "=== 實驗 1 重跑：v13 vs v17（陰跌防禦）===",
        f"窗：{START.date()} → {END.date()}｜SPY50/QQQ50｜$50k",
        "",
        "診斷：v13 的 SPY bench≈69% 中 ~91% 被 sticky 鎖住；harsh_dd 幾乎不觸發（dd60≤−20% 僅 ~0.8%）。",
        "只降 harsh_defense_dd 幾乎無效；v17 = dd門檻 0.10 + harsh_dd 穿透 sticky（thrust 覆寫保留）。",
        "",
        line("v13", v13),
        line("v17", v17),
        f"Δ(v17−v13): ret {d['ret_pp']:+.2f}pp｜maxDD {d['maxdd_pp']:+.2f}pp｜"
        f"SPY cash {d['spy_cash_pp']:+.1f}pp｜SPY bench {d['spy_bench_pp']:+.1f}pp",
        "",
        f"v17 總判決：{'PASS' if v17['verdict']['overall_pass'] else 'FAIL'} "
        f"(MaxDD<22%={'PASS' if v17['verdict']['pass_maxdd'] else 'FAIL'}; "
        f"thrust連擊={'PASS' if v17['verdict']['pass_thrust_harsh'] else 'FAIL'})",
    ]
    txt = "\n".join(lines) + "\n"
    (OUT / f"exp1_rerun_{START.date()}_{END.date()}_zhTW.txt").write_text(txt, encoding="utf-8")
    print("\n" + txt)
    print(f"wrote {out_json}")
    return 0 if v17["verdict"]["overall_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
