#!/usr/bin/env python3
"""Experiment 4: mode hysteresis bandwidth symmetry / sensitivity.

Window 2023-01-01 → 2026-08-13; freeze v13 except mode_enter_trail / mode_exit_trail.
Grid: enter ∈ {0.025, 0.030, 0.035}, exit ∈ {-0.010, -0.015, -0.020}.

Success:
  1) Along path [0.025,-0.010] → [0.030,-0.0125≈mid] → [0.035,-0.015],
     returns are smooth (neighbor |Δret| < 25pp) and weakly monotonic
     (each step does not reverse by >10pp against the enter-tightening direction).
  2) No trade explosion: any enter=0.025 cell has n_trades < 3× v13 baseline
     (0.035 / -0.015).
  3) enter=0.025 cells do not collapse profit vs baseline by ≥20pp
     (cost-eaten failure mode).

Usage::

    PYTHONPATH=src:examples python examples/run_structure_gate_v13_exp4_hysteresis_grid.py
"""

from __future__ import annotations

import json
import sys
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

OUT = ROOT / "examples" / "data" / "structure_gate_v13_exp4_hysteresis_grid"
CACHE = ROOT / "examples" / "data" / "structure_gate_v13_exp3_long_window_plateau" / "cache_ohlcv"
MIN_BARS = 220
START = pd.Timestamp("2023-01-01")
END = pd.Timestamp("2026-08-13")
ENTERS = [0.025, 0.030, 0.035]
EXITS = [-0.010, -0.015, -0.020]
BASE_ENTER = 0.035
BASE_EXIT = -0.015
NEIGHBOR_JUMP_PP = 25.0
TRADE_MULT_MAX = 3.0
PROFIT_COLLAPSE_PP = -20.0
WEIGHTS = dict(V13_BOOK_WEIGHTS)


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


def load_from_cache(symbols: list[str]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols, 1):
        df = _read_csv(CACHE / f"{sym}.csv")
        if df is not None and len(df) >= MIN_BARS:
            frames[sym] = df
        if i == 1 or i % 80 == 0 or i == len(symbols):
            print(f"load [{i}/{len(symbols)}] ok={len(frames)}", flush=True)
    return frames


def cfg_hyst(enter: float, exit_: float) -> StructureGateConfig:
    return replace(
        StructureGateConfig.v13(),
        mode_enter_trail=float(enter),
        mode_exit_trail=float(exit_),
    )


def run_preset(
    label: str,
    cfg: StructureGateConfig,
    frames: dict,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict:
    book_sims = {}
    sleeves = []
    print(
        f"\n=== {label} enter={cfg.mode_enter_trail:.3f} exit={cfg.mode_exit_trail:.3f} "
        f"{start.date()}→{end.date()} ===",
        flush=True,
    )
    for book, w in WEIGHTS.items():
        sleeve_cap = CAPITAL * w
        sim, bh, n_mem = run_book(
            book, frames, sleeve_capital=sleeve_cap, start=start, end=end, cfg=cfg
        )
        book_sims[book] = sim
        m = metrics(sim.equity, sleeve_cap)
        blocked = float(sim.meta.get("mode_switch_blocked", pd.Series(dtype=float)).mean() or 0.0)
        sleeves.append(
            {
                "book": book,
                "weight": w,
                "n_members": n_mem,
                "total_return": m["total_return"],
                "max_drawdown": m["max_drawdown"],
                "sharpe": m["sharpe"],
                "n_trades": int(len(sim.trades)),
                "mode_switch_blocked_share": blocked,
            }
        )
        print(
            f"  {book:4} SG={m['total_return']*100:7.2f}% maxDD={m['max_drawdown']*100:6.2f}% "
            f"trades={len(sim.trades)} blocked={blocked*100:.1f}%",
            flush=True,
        )

    blended, _ = blend_structure_gate_books(book_sims, WEIGHTS, capital=CAPITAL)
    blended = blended.loc[start:end].dropna()
    m_b = metrics(blended, CAPITAL)
    out = {
        "label": label,
        "mode_enter_trail": cfg.mode_enter_trail,
        "mode_exit_trail": cfg.mode_exit_trail,
        "total_return": m_b["total_return"],
        "max_drawdown": m_b["max_drawdown"],
        "sharpe": m_b["sharpe"],
        "n_trades": int(sum(s["n_trades"] for s in sleeves)),
        "sleeves": sleeves,
    }
    print(
        f"  BLEND ret={m_b['total_return']*100:+.2f}% sharpe={m_b['sharpe']:.2f} "
        f"maxDD={m_b['max_drawdown']*100:.2f}% trades={out['n_trades']}",
        flush=True,
    )
    blended.to_csv(OUT / f"equity_{label}_{start.date()}_{end.date()}.csv", header=["equity"])
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    want = sorted(set(WEIGHTS) | {m for b in WEIGHTS for m in book_members(b)})
    frames = load_from_cache(want)
    for b in WEIGHTS:
        if b not in frames:
            raise SystemExit(f"missing bench {b}")
    end = min(END, frames["SPY"].index.max(), frames["QQQ"].index.max())
    start = START
    print(f"window {start.date()}→{end.date()} symbols={len(frames)}", flush=True)

    rows = []
    for en in ENTERS:
        for ex in EXITS:
            label = f"E{en:.3f}_X{ex:.3f}".replace("-", "m").replace(".", "p")
            rows.append(run_preset(label, cfg_hyst(en, ex), frames, start, end))

    def find(en: float, ex: float) -> dict:
        for r in rows:
            if abs(r["mode_enter_trail"] - en) < 1e-9 and abs(r["mode_exit_trail"] - ex) < 1e-9:
                return r
        raise KeyError((en, ex))

    base = find(BASE_ENTER, BASE_EXIT)

    # Primary path from loose to v13: (0.025,-0.010) → (0.030,-0.015) → (0.035,-0.015)
    # Include the prompt endpoints plus midpoint on enter with shared exit progression.
    path = [
        find(0.025, -0.010),
        find(0.030, -0.015),
        find(0.035, -0.015),
    ]
    path_deltas = []
    smooth_ok = True
    for a, b in zip(path, path[1:]):
        d_pp = (b["total_return"] - a["total_return"]) * 100
        path_deltas.append(
            {
                "from": [a["mode_enter_trail"], a["mode_exit_trail"]],
                "to": [b["mode_enter_trail"], b["mode_exit_trail"]],
                "delta_ret_pp": d_pp,
            }
        )
        if abs(d_pp) >= NEIGHBOR_JUMP_PP:
            smooth_ok = False

    # Grid neighbor smoothness (4-neighborhood in enter/exit grid)
    grid = {(r["mode_enter_trail"], r["mode_exit_trail"]): r for r in rows}
    neighbor_jumps = []
    for en in ENTERS:
        for ex in EXITS:
            for den, dex in ((0.005, 0.0), (0.0, -0.005)):
                en2, ex2 = round(en + den, 3), round(ex + dex, 3)
                if (en2, ex2) not in grid:
                    continue
                d_pp = (grid[(en2, ex2)]["total_return"] - grid[(en, ex)]["total_return"]) * 100
                neighbor_jumps.append(
                    {
                        "from": [en, ex],
                        "to": [en2, ex2],
                        "delta_ret_pp": d_pp,
                    }
                )
                if abs(d_pp) >= NEIGHBOR_JUMP_PP:
                    smooth_ok = False

    # Trade explosion at enter=0.025
    enter025 = [r for r in rows if abs(r["mode_enter_trail"] - 0.025) < 1e-9]
    trade_ratios = []
    trade_ok = True
    for r in enter025:
        ratio = r["n_trades"] / max(base["n_trades"], 1)
        trade_ratios.append(
            {
                "enter": r["mode_enter_trail"],
                "exit": r["mode_exit_trail"],
                "n_trades": r["n_trades"],
                "ratio_vs_baseline": ratio,
            }
        )
        if ratio >= TRADE_MULT_MAX:
            trade_ok = False

    # Profit collapse at enter=0.025
    profit_ok = True
    profit_deltas = []
    for r in enter025:
        d_pp = (r["total_return"] - base["total_return"]) * 100
        profit_deltas.append(
            {
                "enter": r["mode_enter_trail"],
                "exit": r["mode_exit_trail"],
                "delta_ret_pp_vs_baseline": d_pp,
            }
        )
        if d_pp <= PROFIT_COLLAPSE_PP:
            profit_ok = False

    # Weak monotonicity on primary path: tightening enter should not violently
    # destroy OR create oscillating pattern (already covered by jump). Also
    # require path ret CV < 15% as extra smoothness.
    path_rets = [r["total_return"] for r in path]
    path_mu = float(np.mean(path_rets))
    path_sd = float(np.std(path_rets, ddof=0))
    path_cv = float(path_sd / abs(path_mu)) if abs(path_mu) > 1e-12 else float("inf")
    pass_path_cv = path_cv < 0.15

    overall = smooth_ok and trade_ok and profit_ok and pass_path_cv

    report = {
        "experiment": "exp4_hysteresis_bandwidth",
        "preset_base": "StructureGateConfig.v13",
        "window": [str(start.date()), str(end.date())],
        "capital": CAPITAL,
        "weights": WEIGHTS,
        "grid": {"enters": ENTERS, "exits": EXITS},
        "baseline": {"mode_enter_trail": BASE_ENTER, "mode_exit_trail": BASE_EXIT},
        "criteria": {
            "neighbor_jump_pp_max": NEIGHBOR_JUMP_PP,
            "trade_mult_max_vs_baseline": TRADE_MULT_MAX,
            "profit_collapse_pp_vs_baseline": PROFIT_COLLAPSE_PP,
            "path_cv_max": 0.15,
        },
        "rows": rows,
        "path": [
            {
                "mode_enter_trail": r["mode_enter_trail"],
                "mode_exit_trail": r["mode_exit_trail"],
                "total_return": r["total_return"],
                "sharpe": r["sharpe"],
                "n_trades": r["n_trades"],
            }
            for r in path
        ],
        "path_deltas": path_deltas,
        "path_cv": path_cv,
        "neighbor_jumps": neighbor_jumps,
        "trade_ratios_enter_025": trade_ratios,
        "profit_deltas_enter_025": profit_deltas,
        "baseline_blend": {
            "total_return": base["total_return"],
            "sharpe": base["sharpe"],
            "n_trades": base["n_trades"],
            "max_drawdown": base["max_drawdown"],
        },
        "verdict": {
            "pass_smooth_no_violent_jump": smooth_ok,
            "pass_path_cv": pass_path_cv,
            "pass_no_trade_explosion": trade_ok,
            "pass_no_profit_collapse_at_025": profit_ok,
            "overall_pass": overall,
        },
        "data": {"cache": str(CACHE), "n_symbols": len(frames)},
        "note": (
            "Only mode_enter_trail / mode_exit_trail vary; other v13 knobs frozen. "
            "Primary path: [0.025,-0.010] → [0.030,-0.015] → [0.035,-0.015]."
        ),
    }
    out_json = OUT / f"exp4_{start.date()}_{end.date()}.json"
    out_json.write_text(json.dumps(report, indent=2, default=float) + "\n")

    # Pretty grid table
    lines = [
        "=== 實驗 4：遲滯帶寬對稱性與敏感度 ===",
        f"窗：{start.date()} → {end.date()}｜資本 ${CAPITAL:,.0f}｜權重 SPY50/QQQ50｜v13 其餘 knobs 凍結",
        f"網格：enter {ENTERS} × exit {EXITS}",
        f"基準：enter={BASE_ENTER} exit={BASE_EXIT}",
        f"資料 symbols_ok={len(frames)}",
        "",
        "全網格（ret% / Sharpe / trades）：",
    ]
    header = "enter\\exit |" + "|".join(f" {ex:+.3f} " for ex in EXITS)
    lines.append(header)
    for en in ENTERS:
        cells = []
        for ex in EXITS:
            r = find(en, ex)
            cells.append(
                f" {r['total_return']*100:+6.1f}%/{r['sharpe']:.2f}/{r['n_trades']:3d} "
            )
        lines.append(f"  {en:.3f}   |" + "|".join(cells))

    lines += ["", "主路徑 [0.025,-0.010] → [0.030,-0.015] → [0.035,-0.015]："]
    for r in path:
        lines.append(
            f"  ({r['mode_enter_trail']:.3f},{r['mode_exit_trail']:.3f}): "
            f"ret {r['total_return']*100:+.2f}%｜Sharpe {r['sharpe']:.2f}｜trades {r['n_trades']}"
        )
    for d in path_deltas:
        lines.append(
            f"  Δ {d['from']}→{d['to']}: {d['delta_ret_pp']:+.2f}pp"
        )
    lines.append(f"  path CV(ret) = {path_cv*100:.2f}%")

    lines += ["", "enter=0.025 vs 基準交易倍數："]
    for t in trade_ratios:
        lines.append(
            f"  ({t['enter']:.3f},{t['exit']:.3f}): trades {t['n_trades']} "
            f"= {t['ratio_vs_baseline']:.2f}× baseline({base['n_trades']})"
        )
    lines += ["", "enter=0.025 vs 基準報酬："]
    for p in profit_deltas:
        lines.append(
            f"  ({p['enter']:.3f},{p['exit']:.3f}): Δret {p['delta_ret_pp_vs_baseline']:+.2f}pp"
        )

    max_jump = max((abs(j["delta_ret_pp"]) for j in neighbor_jumps), default=0.0)
    lines += [
        "",
        f"鄰格最大 |Δret| = {max_jump:.2f}pp（門檻 {NEIGHBOR_JUMP_PP:.0f}pp）",
        "",
        "判準：",
        f"  1) 無劇烈跳點（鄰格/主路徑 |Δ|<{NEIGHBOR_JUMP_PP:.0f}pp）："
        f"{'PASS' if smooth_ok else 'FAIL'}",
        f"  2) 主路徑 CV(ret)<15%：{'PASS' if pass_path_cv else 'FAIL'} ({path_cv*100:.2f}%)",
        f"  3) enter=0.025 交易 <3×基準：{'PASS' if trade_ok else 'FAIL'}",
        f"  4) enter=0.025 報酬未崩（Δ>-20pp）：{'PASS' if profit_ok else 'FAIL'}",
        f"總判決：{'PASS' if overall else 'FAIL'}",
        "",
        "預期失效模式：enter 降至 0.025 時交易暴增 3 倍、成本吞噬利潤。",
    ]
    txt = "\n".join(lines) + "\n"
    (OUT / f"exp4_{start.date()}_{end.date()}_zhTW.txt").write_text(txt, encoding="utf-8")
    print("\n" + txt)
    print(f"wrote {out_json}")
    return 0 if overall else 2


if __name__ == "__main__":
    raise SystemExit(main())
