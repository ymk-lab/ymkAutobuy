#!/usr/bin/env python3
"""Diagnose Structure Gate v13 sleeves: why BENCH, and near-ERS candidates.

Reads the paper OHLCV cache (same as daily job) and writes a zh-TW report with:

1. Per-sleeve mode explanation (flags + trail vs thresholds + v13 hysteresis)
2. Current / would-be ERS pick and top near-miss names (G1 entry conditions)
3. Strong-leader watchlist (already-strong pool)

Usage (on VPS)::

    cd /opt/qresearch
    .venv/bin/python examples/diagnose_structure_gate_v13_sleeves.py
    # optional: TOP=15 .venv/bin/python examples/diagnose_structure_gate_v13_sleeves.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.brokers.futu import load_dotenv_if_present
from qresearch.strategy.emerging_rs_wave import EmergingRSWaveBook, EmergingRSWaveConfig
from qresearch.strategy.structure_gate import (
    V13_BOOK_WEIGHTS,
    StructureGateConfig,
    label_structure_modes,
    strong_leader_weights,
)
from run_structure_gate_v13_paper_daily import (  # type: ignore
    MIN_BARS,
    book_members,
    build_book_panel,
    load_symbol_any,
    out_dir,
)


def _pct(x: float | None, digits: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{100.0 * float(x):+.{digits}f}%"


def _f(x: object) -> float | None:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _num(x: object, digits: int = 2) -> str:
    """Format a float for display; never raise on None/NaN."""
    v = _f(x)
    if v is None:
        return "—"
    return f"{v:.{digits}f}"


def _bool(x: object) -> bool:
    try:
        return bool(float(x))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return bool(x)


def load_frames(cache: Path, books: list[str]) -> dict[str, pd.DataFrame]:
    want = sorted(set(books) | {m for b in books for m in book_members(b)})
    frames: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(want, 1):
        df = load_symbol_any(cache, sym)
        if df is not None and len(df) >= MIN_BARS:
            frames[sym] = df
        if i == 1 or i % 100 == 0 or i == len(want):
            print(f"load [{i}/{len(want)}] ok={len(frames)}", flush=True)
    return frames


def ers_entry_scorecard(
    closes: pd.DataFrame,
    bench_close: pd.Series,
    *,
    cfg: EmergingRSWaveConfig,
    asof: pd.Timestamp,
    top_n: int,
) -> dict:
    """Rank names by G1 ERS entry conditions on ``asof``."""
    px = closes.astype(float).sort_index()
    bench = bench_close.astype(float).reindex(px.index).ffill()
    if asof not in px.index:
        asof = px.index.max()

    stock_ret_s = px / px.shift(cfg.short_window) - 1.0
    stock_ret_m = px / px.shift(cfg.mid_window) - 1.0
    stock_ret_l = px / px.shift(cfg.long_window) - 1.0
    bench_s = bench / bench.shift(cfg.short_window) - 1.0
    bench_m = bench / bench.shift(cfg.mid_window) - 1.0
    bench_l = bench / bench.shift(cfg.long_window) - 1.0
    excess_s = stock_ret_s.sub(bench_s, axis=0)
    excess_m = stock_ret_m.sub(bench_m, axis=0)
    excess_l = stock_ret_l.sub(bench_l, axis=0)

    pos_s = excess_s > 0.0
    persist = pos_s.copy()
    for k in range(1, cfg.persist_days):
        persist = persist & pos_s.shift(k).fillna(False)
    prior_pos = pos_s.shift(cfg.persist_days)
    just_turned = persist & prior_pos.eq(False)
    mid_ok = excess_m > 0.0
    not_already = excess_l <= cfg.already_strong_cap
    entry_ok = just_turned & mid_ok & not_already & persist

    rows: list[dict] = []
    for sym in px.columns:
        es = _f(excess_s.at[asof, sym]) if sym in excess_s.columns else None
        em = _f(excess_m.at[asof, sym]) if sym in excess_m.columns else None
        el = _f(excess_l.at[asof, sym]) if sym in excess_l.columns else None
        if es is None:
            continue
        jt = bool(just_turned.at[asof, sym]) if sym in just_turned.columns else False
        pr = bool(persist.at[asof, sym]) if sym in persist.columns else False
        mo = bool(mid_ok.at[asof, sym]) if sym in mid_ok.columns else False
        na = bool(not_already.at[asof, sym]) if sym in not_already.columns else False
        ok = bool(entry_ok.at[asof, sym]) if sym in entry_ok.columns else False
        # Near-miss score: how many of the 4 entry legs pass; prefer higher excess_20.
        legs = int(jt) + int(pr) + int(mo) + int(na)
        rows.append(
            {
                "symbol": str(sym),
                "entry_ok": ok,
                "legs_pass": legs,
                "just_turned": jt,
                "persist3": pr,
                "excess_mid_ok": mo,
                "not_already_strong": na,
                "excess_20": es,
                "excess_10": em,
                "excess_60": el,
                "gap_to_already_strong_cap": None
                if el is None
                else float(cfg.already_strong_cap) - float(el),
            }
        )

    # Full entry first, then near-miss by legs then excess_20.
    rows.sort(
        key=lambda r: (
            int(r["entry_ok"]),
            int(r["legs_pass"]),
            float(r["excess_20"] or -1e9),
        ),
        reverse=True,
    )
    full = [r for r in rows if r["entry_ok"]]
    near = [r for r in rows if (not r["entry_ok"]) and int(r["legs_pass"]) >= 2]
    return {
        "asof": str(pd.Timestamp(asof).date()),
        "n_entry_ok": len(full),
        "entry_ok_ranked": full[:top_n],
        "near_miss_ranked": near[:top_n],
        "top_by_excess20": sorted(
            rows, key=lambda r: float(r["excess_20"] or -1e9), reverse=True
        )[:top_n],
    }


def explain_mode(row: pd.Series, cfg: StructureGateConfig) -> list[str]:
    """Human reasons (zh-TW) for the stabilized mode on this row."""
    mode = str(row.get("mode", "?"))
    raw = str(row.get("mode_raw", mode))
    trail20 = _f(row.get("leader_vs_bench_trail"))
    trail60 = _f(row.get("leader_vs_bench_trail60"))
    reasons: list[str] = []

    def on(name: str) -> bool:
        return _bool(row.get(name, 0))

    # Priority narrative (matches label_structure_modes).
    if on("harsh_ret"):
        reasons.append(
            f"harsh_ret 開：ret20={_pct(_f(row.get('ret20')))} ≤ "
            f"{_pct(cfg.harsh_defense_ret20)} → 強制 cash（最高優先）"
        )
    if on("thrust"):
        reasons.append(
            "thrust_lock 開：指數短線衝刺 → 鎖 bench（禁止進 ers/strong）"
            f"；ret5={_pct(_f(row.get('ret5')))} ret10={_pct(_f(row.get('ret10')))} "
            f"bounce20={_pct(_f(row.get('bounce20')))} ret20={_pct(_f(row.get('ret20')))}"
        )
    if on("sticky"):
        reasons.append(
            "sticky_lock 開：領導股相對基準落後（60 日 trail）→ 鎖 bench"
            f"；trail60={_pct(trail60)}（進場≤{_pct(cfg.sticky_enter_trail)}，"
            f"出場≥{_pct(cfg.sticky_exit_trail)}）"
        )
    if on("harsh_dd"):
        reasons.append(
            f"harsh_dd 開：dd60={_pct(_f(row.get('dd60')))} ≤ "
            f"{_pct(-cfg.harsh_defense_dd)} → 偏 cash／防守"
        )
    if on("mild"):
        reasons.append(
            f"mild 開：風險未開（above50={_num(row.get('above50'))} "
            f"dd60={_pct(_f(row.get('dd60')))} ret20={_pct(_f(row.get('ret20')))}）"
            " → 非鎖定時傾向 cash，不會開 ers"
        )
    if on("index_lean"):
        reasons.append(
            f"index_lean 開：trail20={_pct(trail20)} ≤ "
            f"{_pct(cfg.index_lean_max_trail)} → 原始偏好 bench（指數偏強／個股沒贏）"
        )
    if on("stock_led"):
        reasons.append(
            f"stock_led 開：trail20={_pct(trail20)} ≥ "
            f"{_pct(cfg.stock_led_min_trail)} → 原始可走個股袖口"
        )
    if on("crowded"):
        reasons.append(
            "crowded 開：集中／重疊偏高 → 若 risk_on 且 stock_led 則原始為 strong"
            f"；top3_conc20={_num(row.get('top3_conc20'))} "
            f"overlap={_num(row.get('overlap'))} "
            f"strong_share={_num(row.get('strong_share'))}"
        )

    if mode == "bench":
        if on("sticky") or on("thrust"):
            reasons.append(
                "結論：sticky／thrust 鎖定優先於 ers/strong → 今日目標 = 基準 ETF 100%"
            )
        elif on("index_lean") and not on("mild") and not on("harsh_ret") and not on("harsh_dd"):
            reasons.append("結論：risk_on + index_lean → 原始／穩定 mode = bench")
        else:
            reasons.append("結論：穩定 mode = bench（見上方旗標）")
    elif mode == "ers":
        reasons.append("結論：風險開、非 index_lean、無 sticky/thrust 鎖 → ers 選股")
    elif mode == "strong":
        reasons.append("結論：stock_led + crowded 且無鎖 → strong 抱已強領導股")
    elif mode == "cash":
        reasons.append("結論：防守／harsh／mild → cash")

    if cfg.mode_hysteresis_enabled and trail20 is not None:
        gap_enter = cfg.mode_enter_trail - trail20
        reasons.append(
            "v13 遲滯："
            f"trail20={_pct(trail20)}｜進 ers/strong 需 ≥ {_pct(cfg.mode_enter_trail)} "
            f"（還差 {_pct(gap_enter)}）｜退回 bench 需 ≤ {_pct(cfg.mode_exit_trail)}｜"
            f"冷靜期 {cfg.mode_switch_cooldown_days} 日"
        )
        if _bool(row.get("mode_switch_blocked", 0)):
            reasons.append(
                f"mode_switch_blocked=1：原始 mode_raw={raw} 被遲滯／冷靜期擋住，"
                f"維持 {mode}"
            )
        elif raw != mode:
            reasons.append(f"mode_raw={raw} → 穩定後 mode={mode}")

    return reasons


def diagnose_book(
    frames: dict[str, pd.DataFrame],
    book: str,
    *,
    cfg: StructureGateConfig,
    top_n: int,
) -> dict:
    closes, bench_close, bench_vol = build_book_panel(frames, book)
    mode, meta = label_structure_modes(
        bench_close, closes, config=cfg, bench_volume=bench_vol
    )
    asof = closes.index.max()
    row = meta.loc[asof]
    m = str(mode.loc[asof])

    ers_cfg = cfg.ers_config or EmergingRSWaveConfig()
    ers_book = EmergingRSWaveBook(gate="G1", config=ers_cfg)
    ers_w, ers_log = ers_book.generate_weights(closes, bench_close)
    ers_row = ers_w.loc[asof]
    ers_active = ers_row[ers_row.abs() > 1e-12]
    ers_pick = str(ers_active.index[0]) if len(ers_active) else None
    ers_pick_w = float(ers_active.iloc[0]) if len(ers_active) else 0.0

    strong_w = strong_leader_weights(closes, bench_close, config=cfg)
    srow = strong_w.loc[asof]
    sactive = srow[srow.abs() > 1e-12]
    strong_pick = str(sactive.index[0]) if len(sactive) else None

    # Already-strong pool snapshot for watchlist context.
    px = closes.astype(float)
    bc = bench_close.astype(float).reindex(px.index).ffill()
    excess60 = (px / px.shift(60) - 1.0).sub(bc / bc.shift(60) - 1.0, axis=0)
    last_ex = excess60.loc[asof].replace([np.inf, -np.inf], np.nan).dropna()
    strong_pool = last_ex[last_ex > cfg.already_strong_cap].sort_values(ascending=False)
    strong_top = [
        {"symbol": str(sym), "excess_60": float(val)}
        for sym, val in strong_pool.head(top_n).items()
    ]

    scorecard = ers_entry_scorecard(
        closes, bench_close, cfg=ers_cfg, asof=asof, top_n=top_n
    )

    recent_events: list[dict] = []
    if len(ers_log):
        lg = ers_log.copy()
        lg["date"] = pd.to_datetime(lg["date"])
        recent = lg[lg["date"] >= (pd.Timestamp(asof) - pd.Timedelta(days=30))]
        recent_events = recent.tail(12).to_dict(orient="records")
        for ev in recent_events:
            if hasattr(ev.get("date"), "isoformat"):
                ev["date"] = str(pd.Timestamp(ev["date"]).date())

    metrics = {
        "asof": str(pd.Timestamp(asof).date()),
        "mode": m,
        "mode_raw": str(row.get("mode_raw", m)),
        "members": int(closes.shape[1]),
        "leader_vs_bench_trail20": _f(row.get("leader_vs_bench_trail")),
        "leader_vs_bench_trail60": _f(row.get("leader_vs_bench_trail60")),
        "ret5": _f(row.get("ret5")),
        "ret10": _f(row.get("ret10")),
        "ret20": _f(row.get("ret20")),
        "bounce20": _f(row.get("bounce20")),
        "dd60": _f(row.get("dd60")),
        "above50": _f(row.get("above50")),
        "pct_beat60": _f(row.get("pct_beat60")),
        "overlap": _f(row.get("overlap")),
        "strong_share": _f(row.get("strong_share")),
        "top3_conc20": _f(row.get("top3_conc20")),
        "ers_excess60": _f(row.get("ers_excess60")),
        "flags": {
            "sticky": _bool(row.get("sticky")),
            "thrust": _bool(row.get("thrust")),
            "mild": _bool(row.get("mild")),
            "harsh_ret": _bool(row.get("harsh_ret")),
            "harsh_dd": _bool(row.get("harsh_dd")),
            "index_lean": _bool(row.get("index_lean")),
            "stock_led": _bool(row.get("stock_led")),
            "crowded": _bool(row.get("crowded")),
            "mode_switch_blocked": _bool(row.get("mode_switch_blocked", 0)),
        },
        "thresholds": {
            "mode_enter_trail": cfg.mode_enter_trail,
            "mode_exit_trail": cfg.mode_exit_trail,
            "mode_switch_cooldown_days": cfg.mode_switch_cooldown_days,
            "stock_led_min_trail": cfg.stock_led_min_trail,
            "index_lean_max_trail": cfg.index_lean_max_trail,
            "sticky_enter_trail": cfg.sticky_enter_trail,
            "sticky_exit_trail": cfg.sticky_exit_trail,
            "already_strong_cap": cfg.already_strong_cap,
        },
        "would_hold_if_ers": {"symbol": ers_pick, "weight": ers_pick_w},
        "would_hold_if_strong": {"symbol": strong_pick, "weight": 1.0 if strong_pick else 0.0},
        "strong_pool_top": strong_top,
        "ers_scorecard": scorecard,
        "ers_events_30d": recent_events,
        "reasons": explain_mode(row, cfg),
    }
    return metrics


def render_zh(report: dict) -> str:
    lines: list[str] = []
    lines.append("=== Structure Gate v13 袖口診斷（為何 BENCH／近 ERS）===")
    lines.append(f"asof={report['asof']}  weights={report['weights']}")
    lines.append(
        "門檻：mode_enter_trail="
        f"{_pct(report['cfg']['mode_enter_trail'])}  "
        f"mode_exit_trail={_pct(report['cfg']['mode_exit_trail'])}  "
        f"stock_led≥{_pct(report['cfg']['stock_led_min_trail'])}  "
        f"index_lean≤{_pct(report['cfg']['index_lean_max_trail'])}"
    )
    lines.append("")

    for book, blk in report["books"].items():
        lines.append("-" * 72)
        lines.append(
            f"## 袖口 {book} ｜ mode={blk['mode']} ｜ mode_raw={blk['mode_raw']} ｜ "
            f"members={blk['members']}"
        )
        flags = blk["flags"]
        on_flags = [k for k, v in flags.items() if v]
        lines.append("旗標 ON：" + (", ".join(on_flags) if on_flags else "（無）"))
        lines.append(
            "關鍵數："
            f"trail20={_pct(blk['leader_vs_bench_trail20'])}  "
            f"trail60={_pct(blk['leader_vs_bench_trail60'])}  "
            f"ret20={_pct(blk['ret20'])}  dd60={_pct(blk['dd60'])}  "
            f"above50={_num(blk.get('above50'))}  pct_beat60={_pct(blk['pct_beat60'])}  "
            f"ers_excess60={_pct(blk['ers_excess60'])}"
        )
        lines.append("解釋：")
        for r in blk["reasons"]:
            lines.append(f"  • {r}")

        wh_ers = blk["would_hold_if_ers"]
        wh_st = blk["would_hold_if_strong"]
        lines.append(
            "若今日是 ers 會抱："
            + (
                f"{wh_ers['symbol']} {wh_ers['weight']:.0%}"
                if wh_ers.get("symbol")
                else "（G1 無進場合格股 → 空倉／無人選）"
            )
        )
        lines.append(
            "若今日是 strong 會抱："
            + (f"{wh_st['symbol']}" if wh_st.get("symbol") else "（無）")
        )

        sc = blk["ers_scorecard"]
        lines.append(
            f"G1 進場合格數 n_entry_ok={sc['n_entry_ok']}（需：剛轉強 persist3 + mid超額>0 + "
            f"excess60≤{report['cfg']['already_strong_cap']:.0%}）"
        )
        if sc["entry_ok_ranked"]:
            lines.append("今日 ERS 合格（依 excess_20 排序）：")
            for i, r in enumerate(sc["entry_ok_ranked"][:10], 1):
                lines.append(
                    f"  {i:2d}. {r['symbol']:<6}  ex20={_pct(r['excess_20'])}  "
                    f"ex10={_pct(r['excess_10'])}  ex60={_pct(r['excess_60'])}"
                )
        else:
            lines.append("今日 ERS 合格：無")

        if sc["near_miss_ranked"]:
            lines.append("接近 ERS（≥2/4 條件，尚未合格）— 最值得盯：")
            for i, r in enumerate(sc["near_miss_ranked"][:10], 1):
                miss = []
                if not r["just_turned"]:
                    miss.append("缺just_turned")
                if not r["persist3"]:
                    miss.append("缺persist3")
                if not r["excess_mid_ok"]:
                    miss.append("缺mid+")
                if not r["not_already_strong"]:
                    miss.append("已過強(ex60高)")
                lines.append(
                    f"  {i:2d}. {r['symbol']:<6}  legs={r['legs_pass']}/4  "
                    f"ex20={_pct(r['excess_20'])}  ex10={_pct(r['excess_10'])}  "
                    f"ex60={_pct(r['excess_60'])}  缺：{','.join(miss) or '—'}"
                )
        else:
            lines.append("接近 ERS：無（多數連 2 腿都不到）")

        if blk["strong_pool_top"]:
            lines.append("已強池 top（excess60 > already_strong_cap，strong mode 候選）：")
            for i, r in enumerate(blk["strong_pool_top"][:8], 1):
                lines.append(f"  {i:2d}. {r['symbol']:<6}  ex60={_pct(r['excess_60'])}")

        if blk["ers_events_30d"]:
            lines.append("近 30 日 G1 事件（進出）：")
            for ev in blk["ers_events_30d"][-8:]:
                lines.append(
                    f"  {ev.get('date')} {ev.get('action')} {ev.get('symbol')} "
                    f"reason={ev.get('reason')} ex20={_pct(_f(ev.get('excess_20')))}"
                )
        lines.append("")

    lines.append("=== END ===")
    return "\n".join(lines)


def main() -> int:
    load_dotenv_if_present(ROOT / ".env")
    top_n = int(os.getenv("TOP", "12"))
    books = list(V13_BOOK_WEIGHTS)
    base = out_dir()
    cache = base / "cache_ohlcv"
    # Also allow reading v11 cache via load_symbol_any fallbacks inside paper daily.
    print(f"out={base}", flush=True)
    print(f"cache={cache} exists={cache.is_dir()}", flush=True)

    frames = load_frames(cache, books)
    for b in books:
        if b not in frames:
            print(f"missing bench {b}", file=sys.stderr)
            return 1

    cfg = StructureGateConfig.v13()
    book_reports = {}
    asof = None
    for book in books:
        print(f"diagnose {book}…", flush=True)
        blk = diagnose_book(frames, book, cfg=cfg, top_n=top_n)
        book_reports[book] = blk
        asof = blk["asof"]

    report = {
        "asof": asof,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "weights": dict(V13_BOOK_WEIGHTS),
        "cfg": {
            "mode_enter_trail": cfg.mode_enter_trail,
            "mode_exit_trail": cfg.mode_exit_trail,
            "mode_switch_cooldown_days": cfg.mode_switch_cooldown_days,
            "stock_led_min_trail": cfg.stock_led_min_trail,
            "index_lean_max_trail": cfg.index_lean_max_trail,
            "already_strong_cap": cfg.already_strong_cap,
            "sticky_enter_trail": cfg.sticky_enter_trail,
            "sticky_exit_trail": cfg.sticky_exit_trail,
        },
        "books": book_reports,
    }

    text = render_zh(report)
    out_json = base / f"sleeve_diagnose_{asof}.json"
    out_txt = base / f"sleeve_diagnose_{asof}.txt"
    payload = json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n"
    out_json.write_text(payload, encoding="utf-8")
    out_txt.write_text(text + "\n", encoding="utf-8")
    (base / "latest_sleeve_diagnose.json").write_text(payload, encoding="utf-8")
    (base / "latest_sleeve_diagnose.txt").write_text(text + "\n", encoding="utf-8")

    print("\n" + text)
    print(f"\nwrote {out_txt}")
    print(f"wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
