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
CHUNK_DAYS = 7  # stay under Longbridge ~1000-bar cap for 5m
BENCHES = ["SPY", "QQQ", "SMH"]
# Longbridge US history quota often blocks SPY; fall back listed here.
LB_SYMBOLS = ["QQQ", "SMH"]
PROXY_RATIO = {"SPY": "QQQ"}


def _iter_chunks(start: date, end: date, step_days: int):
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=step_days - 1), end)
        yield cur, nxt
        cur = nxt + timedelta(days=1)


def _candles_to_store(candles, sym: str, store: dict[pd.Timestamp, dict[str, float]]) -> int:
    n = 0
    for c in candles:
        ts = pd.Timestamp(c.timestamp)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC").tz_convert(ET)
        else:
            ts = ts.tz_convert(ET)
        hm = ts.strftime("%H:%M")
        if hm not in {"09:30", "09:40"}:
            continue
        day = pd.Timestamp(datetime(ts.year, ts.month, ts.day))
        key = f"{sym}_{hm.replace(':', '')}"
        store.setdefault(day, {})[key] = float(c.open)
        n += 1
    return n


def fetch_longbridge_symbol(
    ctx,
    sym: str,
    start: date,
    end: date,
    store: dict[pd.Timestamp, dict[str, float]],
) -> int:
    from longbridge.openapi import AdjustType, Period, TradeSessions

    code = f"{sym}.US"
    n_bars = 0
    for a, b in _iter_chunks(start, end, CHUNK_DAYS):
        candles = None
        for attempt in range(4):
            try:
                candles = list(
                    ctx.history_candlesticks_by_date(
                        code,
                        Period.Min_5,
                        AdjustType.NoAdjust,
                        start=a,
                        end=b,
                        trade_sessions=TradeSessions.Intraday,
                    )
                )
                break
            except Exception as exc:  # noqa: BLE001
                wait = 2.0 * (attempt + 1)
                print(f"  retry {sym} {a}→{b}: {exc} sleep={wait:.1f}s", flush=True)
                time.sleep(wait)
        if candles is None:
            raise RuntimeError(f"failed {sym} {a}→{b}")
        n_bars += len(candles)
        _candles_to_store(candles, sym, store)
        print(f"  {sym} chunk {a}→{b} bars={len(candles)}", flush=True)
        time.sleep(0.12)
    return n_bars


def fetch_yahoo_symbol(
    sym: str,
    store: dict[pd.Timestamp, dict[str, float]],
) -> int:
    """Yahoo 5m — last ~60 calendar days only."""
    import yfinance as yf

    raw = yf.Ticker(sym).history(period="60d", interval="5m", auto_adjust=False)
    if raw is None or raw.empty:
        print(f"  yahoo {sym}: empty", flush=True)
        return 0
    idx = raw.index
    if idx.tz is None:
        idx = idx.tz_localize(ET)
    else:
        idx = idx.tz_convert(ET)
    n = 0
    for ts, row in zip(idx, raw.itertuples(index=False)):
        hm = ts.strftime("%H:%M")
        if hm not in {"09:30", "09:40"}:
            continue
        day = pd.Timestamp(datetime(ts.year, ts.month, ts.day))
        key = f"{sym}_{hm.replace(':', '')}"
        store.setdefault(day, {})[key] = float(row.Open)
        n += 1
    print(f"  yahoo {sym}: stamps={n} range={idx.min().date()}→{idx.max().date()}", flush=True)
    return n


def fetch_bench_entry_opens(
    start: date,
    end: date,
    *,
    cache_path: Path,
) -> tuple[pd.DataFrame, dict]:
    """Return DataFrame index=date with columns like SPY_0930, SPY_0940, …"""
    meta: dict = {
        "longbridge_symbols": list(LB_SYMBOLS),
        "yahoo_symbols": ["SPY"],
        "ratio_proxy": dict(PROXY_RATIO),
    }
    if cache_path.is_file():
        df = pd.read_csv(cache_path, parse_dates=["date"]).set_index("date")
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        need = [f"{b}_{t}" for b in BENCHES for t in ("0930", "0940")]
        # QQQ/SMH must cover window; SPY may be partial (proxied)
        core_ok = (
            "QQQ_0930" in df.columns
            and "QQQ_0940" in df.columns
            and "SMH_0930" in df.columns
            and "SMH_0940" in df.columns
            and df.index.min().date() <= start
            and df.index.max().date() >= end
            and int(df["QQQ_0930"].notna().sum()) >= 200
        )
        if core_ok:
            print(f"reuse cache {cache_path} rows={len(df)}", flush=True)
            return df, meta

    from longbridge.openapi import QuoteContext

    ctx = QuoteContext(load_longbridge_config())
    store: dict[pd.Timestamp, dict[str, float]] = {}

    for sym in LB_SYMBOLS:
        n = fetch_longbridge_symbol(ctx, sym, start, end, store)
        print(f"{sym} longbridge bars≈{n}", flush=True)

    fetch_yahoo_symbol("SPY", store)

    if not store:
        raise SystemExit("no 09:30/09:40 bars fetched")
    df = pd.DataFrame.from_dict(store, orient="index").sort_index()
    df.index.name = "date"
    # ensure columns exist
    for b in BENCHES:
        for t in ("0930", "0940"):
            col = f"{b}_{t}"
            if col not in df.columns:
                df[col] = pd.NA
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path)
    print(f"wrote {cache_path} rows={len(df)}", flush=True)
    return df, meta


def entry_ratio(entry: pd.DataFrame, bench: str) -> pd.Series:
    o930 = entry.get(f"{bench}_0930")
    o940 = entry.get(f"{bench}_0940")
    if o930 is None or o940 is None:
        r = pd.Series(1.0, index=entry.index)
    else:
        r = (o940 / o930).where(o930.notna() & o940.notna() & (o930 > 0))
    proxy = PROXY_RATIO.get(bench)
    if proxy:
        p930 = entry[f"{proxy}_0930"]
        p940 = entry[f"{proxy}_0940"]
        pr = (p940 / p930).where(p930.notna() & p940.notna() & (p930 > 0))
        r = r.fillna(pr)
        # if SPY has no stamps at all, fully use proxy
        if o930 is None or o930.notna().sum() == 0:
            r = pr
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

    print(f"fetch 5m entry opens {START}→{END}", flush=True)
    entry, fetch_meta = fetch_bench_entry_opens(
        START,
        END,
        cache_path=OUT / "bench_entry_opens_5m.csv",
    )
    # clip to window
    entry = entry.loc[str(START) : str(END)]
    for b in BENCHES:
        c930, c940 = f"{b}_0930", f"{b}_0940"
        if c930 not in entry.columns:
            print(f"  {b}: no columns (will proxy if configured)", flush=True)
            continue
        both = entry[c930].notna() & entry[c940].notna()
        print(
            f"  {b}: days_indexed={len(entry)} with_both={int(both.sum())} "
            f"proxy={PROXY_RATIO.get(b)}",
            flush=True,
        )

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
            "bars": "5m open at 09:30 and 09:40 ET",
            "sources": fetch_meta,
            "0930": "cache daily open (unchanged)",
            "0940": "daily open * (bench_0940_open / bench_0930_open) per sleeve",
            "marks": "daily close unchanged; fees/slippage same as v11",
            "note": "SPY Longbridge history often quota-blocked; Yahoo ~60d + QQQ ratio proxy for older SPY days",
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
