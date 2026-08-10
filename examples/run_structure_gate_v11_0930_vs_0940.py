#!/usr/bin/env python3
"""Structure Gate v11: next-open at 09:30 vs 09:40 (2025-08-07→2026-08-07).

Signals still use daily closes. Only *execution opens* change:

- ``0930``: keep cache daily open (backtest default ≈ RTH open)
- ``0940``: scale each book's opens by that day's bench ``open_0940/open_0930``
  from Longbridge 5-minute bars (stock-level 1m not required)

Test / research only — not wired into paper cron.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.brokers.longbridge.config import load_longbridge_config
from qresearch.strategy.regime_playbook import simulate_bench_bh
from qresearch.strategy.structure_gate import (
    V11_BOOK_WEIGHTS,
    StructureGateConfig,
    blend_structure_gate_books,
    simulate_structure_gate,
)
from run_emerging_rs_wave_gates import metrics  # type: ignore
from run_structure_gate_v11_blend import (  # type: ignore
    CAPITAL,
    WEIGHTS,
    align_panel,
    book_members,
    load_many,
)

ET = ZoneInfo("America/New_York")
OUT = ROOT / "examples" / "data" / "structure_gate_v11_entry_time"
START = date(2025, 8, 7)
END = date(2026, 8, 7)
CHUNK_DAYS = 10  # stay under Longbridge ~1000-bar cap for 5m
BENCHES = ["SPY", "QQQ", "SMH"]


def _iter_chunks(start: date, end: date, step_days: int):
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=step_days - 1), end)
        yield cur, nxt
        cur = nxt + timedelta(days=1)


def fetch_bench_entry_opens(
    symbols: list[str],
    start: date,
    end: date,
    *,
    cache_path: Path,
) -> pd.DataFrame:
    """Return DataFrame index=date with columns like SPY_0930, SPY_0940, …"""
    if cache_path.is_file():
        df = pd.read_csv(cache_path, parse_dates=["date"]).set_index("date")
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        # accept cache if it covers the window
        if df.index.min().date() <= start and df.index.max().date() >= end:
            print(f"reuse cache {cache_path} rows={len(df)}", flush=True)
            return df

    from longbridge.openapi import AdjustType, Period, QuoteContext, TradeSessions

    ctx = QuoteContext(load_longbridge_config())
    # date -> {sym: {0930: px, 0940: px}}
    store: dict[pd.Timestamp, dict[str, float]] = {}

    for sym in symbols:
        code = f"{sym}.US"
        n_bars = 0
        for a, b in _iter_chunks(start, end, CHUNK_DAYS):
            for attempt in range(3):
                try:
                    candles = list(
                        ctx.history_candlesticks_by_date(
                            code,
                            Period.Min_5,
                            AdjustType.NoAdjust,
                            a,
                            b,
                            TradeSessions.Intraday,
                        )
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    wait = 1.5 * (attempt + 1)
                    print(f"  retry {sym} {a}→{b}: {exc} sleep={wait:.1f}s", flush=True)
                    time.sleep(wait)
            else:
                raise RuntimeError(f"failed {sym} {a}→{b}")
            n_bars += len(candles)
            for c in candles:
                ts = pd.Timestamp(c.timestamp)
                if ts.tzinfo is None:
                    # Longbridge timestamps are UTC
                    ts = ts.tz_localize("UTC").tz_convert(ET)
                else:
                    ts = ts.tz_convert(ET)
                hm = ts.strftime("%H:%M")
                if hm not in {"09:30", "09:40"}:
                    continue
                day = pd.Timestamp(ts.date())
                key = f"{sym}_{hm.replace(':', '')}"
                store.setdefault(day, {})[key] = float(c.open)
            print(
                f"  {sym} chunk {a}→{b} bars+={len(candles)} days={len(store)}",
                flush=True,
            )
            time.sleep(0.15)
        print(f"{sym} done bars≈{n_bars}", flush=True)

    if not store:
        raise SystemExit("no 09:30/09:40 bars fetched")
    df = pd.DataFrame.from_dict(store, orient="index").sort_index()
    df.index.name = "date"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path)
    print(f"wrote {cache_path} rows={len(df)}", flush=True)
    return df


def entry_ratio(entry: pd.DataFrame, bench: str) -> pd.Series:
    o930 = entry[f"{bench}_0930"]
    o940 = entry[f"{bench}_0940"]
    r = (o940 / o930).where(o930.notna() & o940.notna() & (o930 > 0))
    return r.reindex(entry.index).fillna(1.0).rename(f"{bench}_r940")


def scale_frames(
    frames: dict[str, pd.DataFrame],
    *,
    book: str,
    ratio: pd.Series,
) -> dict[str, pd.DataFrame]:
    """Copy frames; multiply open by book-bench ratio on matching dates."""
    r = ratio.copy()
    r.index = pd.to_datetime(r.index).tz_localize(None).normalize()
    out: dict[str, pd.DataFrame] = {}
    members = set(book_members(book)) | {book}
    for sym, df in frames.items():
        if sym not in members:
            out[sym] = df
            continue
        d = df.copy()
        scale = r.reindex(d.index).fillna(1.0).astype(float)
        d["open"] = d["open"].astype(float) * scale.to_numpy()
        out[sym] = d
    return out


def run_book(book: str, frames: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp):
    cfg = StructureGateConfig.v11()
    bdf = frames[book].loc[:end]
    opens, closes = align_panel(frames, book_members(book), bdf.index)
    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    sim = simulate_structure_gate(
        opens,
        closes,
        bdf["open"],
        bdf["close"],
        capital=CAPITAL * WEIGHTS[book],
        start=start,
        fees=fees,
        config=cfg,
        bench_volume=bdf["volume"] if "volume" in bdf.columns else None,
    )
    return sim


def run_variant(
    label: str,
    frames: dict[str, pd.DataFrame],
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    entry: pd.DataFrame | None = None,
    scale_to_0940: bool = False,
) -> dict:
    book_sims = {}
    sleeves = []
    for book, w in WEIGHTS.items():
        book_frames = frames
        if scale_to_0940:
            assert entry is not None
            book_frames = scale_frames(frames, book=book, ratio=entry_ratio(entry, book))
        sim = run_book(book, book_frames, start, end)
        book_sims[book] = sim
        m = metrics(sim.equity, CAPITAL * w)
        sleeves.append(
            {
                "book": book,
                "weight": w,
                "total_return": m["total_return"],
                "max_drawdown": m["max_drawdown"],
                "sharpe": m["sharpe"],
                "end_equity": m["end_equity"],
                "n_trades": int(len(sim.trades)),
            }
        )
        print(
            f"  [{label}] {book}: ret={m['total_return']*100:.2f}% "
            f"maxDD={m['max_drawdown']*100:.2f}% trades={len(sim.trades)}",
            flush=True,
        )
    blended, _ = blend_structure_gate_books(book_sims, WEIGHTS, capital=CAPITAL)
    blended = blended.loc[start:end].dropna()
    m_b = metrics(blended, CAPITAL)
    fees = FutuUsEquityFees(slippage_bps=StructureGateConfig.v11().bench_slippage_bps)
    # SPY B&H uses the same execution open convention as the variant label
    spy_frames = frames
    if scale_to_0940:
        assert entry is not None
        spy_frames = scale_frames(frames, book="SPY", ratio=entry_ratio(entry, "SPY"))
    spy = spy_frames["SPY"]
    eq_bh = simulate_bench_bh(
        spy["open"], spy["close"], capital=CAPITAL, start=start, fees=fees
    ).reindex(blended.index).ffill()
    m_bh = metrics(eq_bh, CAPITAL)
    tag = f"{start.date()}_{end.date()}"
    blended.to_csv(OUT / f"equity_{label}_{tag}.csv", header=["equity"])
    return {
        "label": label,
        "blend": {
            "total_return": m_b["total_return"],
            "max_drawdown": m_b["max_drawdown"],
            "sharpe": m_b["sharpe"],
            "end_equity": m_b["end_equity"],
            "vs_spy_bh_pp": (m_b["total_return"] - m_bh["total_return"]) * 100,
        },
        "spy_bh": m_bh,
        "sleeves": sleeves,
    }


def ratio_stats(entry: pd.DataFrame) -> dict:
    rows = []
    for b in BENCHES:
        r = entry_ratio(entry, b)
        bps = (r - 1.0) * 10000.0
        rows.append(
            {
                "bench": b,
                "n": int(bps.notna().sum()),
                "mean_bps": float(bps.mean()),
                "abs_mean_bps": float(bps.abs().mean()),
                "median_bps": float(bps.median()),
                "p05_bps": float(bps.quantile(0.05)),
                "p95_bps": float(bps.quantile(0.95)),
                "min_bps": float(bps.min()),
                "max_bps": float(bps.max()),
            }
        )
    return {"per_bench_0940_vs_0930": rows}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    start_ts = pd.Timestamp(START)
    end_ts = pd.Timestamp(END)

    print(f"fetch Longbridge 5m entry opens {START}→{END}", flush=True)
    entry = fetch_bench_entry_opens(
        BENCHES,
        START,
        END,
        cache_path=OUT / "bench_entry_opens_5m.csv",
    )
    # clip to window
    entry = entry.loc[str(START) : str(END)]
    # require both stamps
    for b in BENCHES:
        miss = entry[f"{b}_0930"].isna() | entry[f"{b}_0940"].isna()
        print(f"  {b}: days={len(entry)} missing_either={int(miss.sum())}", flush=True)

    stats = ratio_stats(entry)
    print("\n09:40 open vs 09:30 open (bps):", flush=True)
    for row in stats["per_bench_0940_vs_0930"]:
        print(
            f"  {row['bench']}: mean={row['mean_bps']:+.2f} abs_mean={row['abs_mean_bps']:.2f} "
            f"p05/p95={row['p05_bps']:+.1f}/{row['p95_bps']:+.1f} "
            f"range=[{row['min_bps']:+.1f},{row['max_bps']:+.1f}] n={row['n']}",
            flush=True,
        )

    want = sorted(
        set(BENCHES)
        | set(book_members("QQQ"))
        | set(book_members("SMH"))
        | set(book_members("SPY"))
    )
    print(f"\nloading {len(want)} daily symbols…", flush=True)
    frames = load_many(want)
    for b in BENCHES:
        if b not in frames:
            raise SystemExit(f"missing daily cache for {b}")

    print("\n=== variant 0930 (daily open) ===", flush=True)
    r0930 = run_variant("0930", frames, start_ts, end_ts)

    print("\n=== variant 0940 (scaled by bench 5m) ===", flush=True)
    r0940 = run_variant(
        "0940", frames, start_ts, end_ts, entry=entry, scale_to_0940=True
    )

    d_ret = (r0940["blend"]["total_return"] - r0930["blend"]["total_return"]) * 100
    d_dd = (r0940["blend"]["max_drawdown"] - r0930["blend"]["max_drawdown"]) * 100
    summary = {
        "ok": True,
        "window": {"start": str(START), "end": str(END)},
        "method": {
            "bars": "Longbridge 5m open at 09:30 and 09:40 ET",
            "0930": "cache daily open (unchanged)",
            "0940": "daily open * (bench_0940_open / bench_0930_open) per sleeve",
            "marks": "daily close unchanged; fees/slippage same as v11",
        },
        "entry_move_stats": stats,
        "variants": {"0930": r0930, "0940": r0940},
        "delta_0940_minus_0930": {
            "blend_total_return_pp": d_ret,
            "blend_max_drawdown_pp": d_dd,
            "sleeves_pp": {
                a["book"]: (b["total_return"] - a["total_return"]) * 100
                for a, b in zip(r0930["sleeves"], r0940["sleeves"])
            },
        },
    }
    out_path = OUT / "summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=float) + "\n")
    print(
        f"\nBLEND 0930={r0930['blend']['total_return']*100:.2f}% "
        f"0940={r0940['blend']['total_return']*100:.2f}% "
        f"Δ={d_ret:+.2f}pp  maxDD Δ={d_dd:+.2f}pp",
        flush=True,
    )
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
