#!/usr/bin/env python3
"""v13：ers/strong 解鎖後是否真的有標的可落單？

統計視窗內每個袖口：
- mode=ers/strong 的天數
- 其中「有標的」(weights 非空) vs「空池」(開了鎖但沒股票可買 → 持現金)
- 實際 BUY 筆數（ers_enter / strong_enter）與 flat 清倉筆數

Usage (VPS paper cache)::

    cd /opt/qresearch
    .venv/bin/python examples/report_v13_ers_strong_fill.py 2025-08-07 2026-08-13
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.strategy.emerging_rs_wave import EmergingRSWaveBook, EmergingRSWaveConfig
from qresearch.strategy.structure_gate import (
    StructureGateConfig,
    strong_leader_weights,
)
from run_structure_gate_v13_blend import (  # type: ignore
    CAPITAL,
    OUT,
    WEIGHTS,
    book_members,
    load_many,
    run_book,
)

OUT_DIR = OUT / "ers_strong_fill"


def _active(weights_row: pd.Series) -> tuple[str | None, float]:
    active = weights_row[weights_row.abs() > 1e-12]
    if len(active) == 0:
        return None, 0.0
    return str(active.index[0]), float(active.iloc[0])


def analyze_sleeve(book: str, sim, frames: dict, cfg: StructureGateConfig, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    bdf = frames[book]
    members = [m for m in book_members(book) if m in frames]
    closes = pd.DataFrame({s: frames[s]["close"] for s in members}).reindex(bdf.index)
    closes = closes.loc[:end]
    bench_close = bdf["close"].reindex(closes.index)

    ers_book = EmergingRSWaveBook(gate="G1", config=cfg.ers_config or EmergingRSWaveConfig())
    ers_w, _ = ers_book.generate_weights(closes, bench_close)
    strong_w = strong_leader_weights(closes, bench_close, config=cfg)
    ers_w = ers_w.reindex(closes.index).fillna(0.0)
    strong_w = strong_w.reindex(closes.index).fillna(0.0)

    mode = sim.mode.astype(str)
    idx = mode.index[(mode.index >= start) & (mode.index <= end)]
    mode = mode.reindex(idx)

    rows = []
    for dt in idx:
        m = mode.at[dt]
        if m not in ("ers", "strong"):
            continue
        wdf = strong_w if m == "strong" else ers_w
        sym, w = _active(wdf.loc[dt]) if dt in wdf.index else (None, 0.0)
        rows.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "mode": m,
                "target": sym,
                "weight": float(w),
                "has_target": sym is not None and w > 0,
            }
        )

    detail = pd.DataFrame(rows)
    n_mode = int(len(detail))
    n_filled = int(detail["has_target"].sum()) if n_mode else 0
    n_empty = n_mode - n_filled

    by_mode = {}
    for m in ("ers", "strong"):
        sub = detail[detail["mode"] == m] if n_mode else detail
        nf = int(sub["has_target"].sum()) if len(sub) else 0
        by_mode[m] = {
            "days": int(len(sub)),
            "days_with_target": nf,
            "days_empty": int(len(sub)) - nf,
            "empty_share": (1.0 - nf / len(sub)) if len(sub) else None,
            "top_targets": Counter(sub.loc[sub["has_target"], "target"]).most_common(8),
        }

    trades = sim.trades.copy() if sim.trades is not None and len(sim.trades) else pd.DataFrame()
    if len(trades):
        trades["date"] = pd.to_datetime(trades["date"])
        trades = trades[(trades["date"] >= start) & (trades["date"] <= end)]
    enter = trades[trades["reason"].isin(["ers_enter", "strong_enter"])] if len(trades) else trades
    flat = trades[trades["reason"].isin(["ers_flat", "strong_flat"])] if len(trades) else trades
    rotate = trades[trades["reason"].isin(["ers_rotate", "strong_rotate"])] if len(trades) else trades

    empty_dates = (
        detail.loc[~detail["has_target"], ["date", "mode"]].to_dict("records") if n_empty else []
    )

    return {
        "book": book,
        "n_days_total": int(len(idx)),
        "mode_share": mode.value_counts(normalize=True).to_dict(),
        "stock_mode_days": n_mode,
        "stock_mode_days_with_target": n_filled,
        "stock_mode_days_empty": n_empty,
        "empty_share_of_stock_mode": (n_empty / n_mode) if n_mode else None,
        "by_mode": by_mode,
        "buys_enter": int(len(enter)),
        "buys_by_reason": dict(Counter(enter["reason"])) if len(enter) else {},
        "buys_by_symbol": Counter(enter["symbol"]).most_common(20) if len(enter) else [],
        "flat_events": int(len(flat)),
        "flat_by_reason": dict(Counter(flat["reason"])) if len(flat) else {},
        "rotate_events": int(len(rotate)),
        "empty_dates_sample": empty_dates[:25],
        "n_trades": int(len(trades)),
    }


def main() -> int:
    start = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2025-08-07")
    end = pd.Timestamp(sys.argv[2] if len(sys.argv) > 2 else "2026-08-13")
    want = sorted(set(WEIGHTS) | {m for b in WEIGHTS for m in book_members(b)})
    print(f"loading {len(want)} symbols…", flush=True)
    frames = load_many(want)
    for b in WEIGHTS:
        if b not in frames:
            raise SystemExit(f"missing {b}")

    cfg = StructureGateConfig.v13()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "start": str(start.date()),
        "end": str(end.date()),
        "capital": CAPITAL,
        "weights": dict(WEIGHTS),
        "rule": "StructureGateConfig.v13()",
        "note": (
            "mode=ers/strong 只代表鎖開；若當日 G1/strong 權重為空，"
            "引擎不會 BUY（或 ers_flat/strong_flat 清倉），帳上等同現金。"
        ),
        "sleeves": {},
    }

    print(f"\n=== v13 ers/strong 落單檢查 {start.date()}→{end.date()} ===\n")
    for book, w in WEIGHTS.items():
        sleeve_cap = CAPITAL * w
        sim, _, n_mem = run_book(
            book, frames, sleeve_capital=sleeve_cap, start=start, end=end, cfg=cfg
        )
        stats = analyze_sleeve(book, sim, frames, cfg, start, end)
        stats["weight"] = w
        stats["n_members"] = n_mem
        report["sleeves"][book] = stats

        print(f"## {book} (w={w:.0%}, n={n_mem})")
        print(f"  mode 佔比: { {k: round(v*100,1) for k,v in stats['mode_share'].items()} }")
        print(
            f"  ers+strong 天數={stats['stock_mode_days']}｜"
            f"有標的={stats['stock_mode_days_with_target']}｜"
            f"空池={stats['stock_mode_days_empty']} "
            f"({100*(stats['empty_share_of_stock_mode'] or 0):.1f}% 開鎖無單)"
        )
        for m, b in stats["by_mode"].items():
            if b["days"] == 0:
                continue
            print(
                f"    {m}: {b['days']}d｜有標的 {b['days_with_target']}｜空池 {b['days_empty']}"
            )
        print(
            f"  實際 BUY enter={stats['buys_enter']} {stats['buys_by_reason']}｜"
            f"flat={stats['flat_events']} {stats['flat_by_reason']}｜"
            f"rotate={stats['rotate_events']}"
        )
        if stats["buys_by_symbol"]:
            print(f"  enter 標的: {stats['buys_by_symbol'][:10]}")
        if stats["empty_dates_sample"]:
            print(f"  空池樣例: {stats['empty_dates_sample'][:8]}")
        print()

    out_json = OUT_DIR / f"fill_{start.date()}_{end.date()}.json"
    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
