#!/usr/bin/env python3
"""Structure Gate v13 calendar-year bakeoff, 2019 through 2026.

Production weights: SPY 50% / QQQ 50%. Knobs: StructureGateConfig.v13().
Each year is an independent $50k start (not compounded across years).
Warm-up bars come from prior calendar years in the same cache.

Usage:
  python examples/run_structure_gate_v13_yearly.py
  python examples/run_structure_gate_v13_yearly.py --start-year 2019 --end-year 2026
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

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
from run_structure_gate_v11_blend import book_members, run_book  # type: ignore

OUT = ROOT / "examples" / "data" / "structure_gate_v13_yearly"
CACHE = OUT / "cache_ohlcv"
CAPITAL = 50_000.0
WEIGHTS = dict(V13_BOOK_WEIGHTS)  # SPY 0.5 / QQQ 0.5
MIN_BARS = 220
YF_START = "2018-01-01"


def _yf_chart(symbol: str, start: str, end: str | None = None) -> pd.DataFrame | None:
    period1 = int(pd.Timestamp(start).timestamp())
    period2 = int(pd.Timestamp(end or pd.Timestamp.utcnow().normalize()).timestamp())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{symbol}?period1={period1}&period2={period2}&interval=1d&events=div%2Csplit"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 qresearch-v13-yearly"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    try:
        result = payload["chart"]["result"][0]
        ts = result["timestamp"]
        q = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError):
        return None
    df = pd.DataFrame(
        {
            "open": q.get("open"),
            "high": q.get("high"),
            "low": q.get("low"),
            "close": q.get("close"),
            "volume": q.get("volume"),
        },
        index=pd.to_datetime(ts, unit="s"),
    )
    df = df.dropna(how="any")
    if df.empty:
        return None
    df.index = df.index.tz_localize(None).normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    try:
        return validate_ohlcv(df)
    except Exception:
        return None


def cache_path(sym: str) -> Path:
    return CACHE / f"{sym}.csv"


def load_cached(sym: str) -> pd.DataFrame | None:
    path = cache_path(sym)
    if not path.is_file():
        return None
    try:
        raw = pd.read_csv(path, index_col=0, parse_dates=True)
        raw.columns = [str(c).lower() for c in raw.columns]
        df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        df = df[~df.index.duplicated(keep="last")].sort_index()
        return df if len(df) >= 60 else None
    except Exception:
        return None


def ensure_symbol(sym: str) -> pd.DataFrame | None:
    cached = load_cached(sym)
    if cached is not None and len(cached) >= MIN_BARS and cached.index.min() <= pd.Timestamp("2018-06-01"):
        return cached
    df = _yf_chart(sym, YF_START)
    if df is None or len(df) < 60:
        return cached
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path(sym))
    return df


def load_universe(symbols: list[str]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols, 1):
        df = ensure_symbol(sym)
        if df is not None and len(df) >= MIN_BARS:
            frames[sym] = df
        if i == 1 or i % 40 == 0 or i == len(symbols) or sym in WEIGHTS:
            print(f"load [{i}/{len(symbols)}] ok={len(frames)} last={sym}", flush=True)
        time.sleep(0.05)
    return frames


def run_year(year: int, frames: dict[str, pd.DataFrame], cfg: StructureGateConfig) -> dict:
    start = pd.Timestamp(f"{year}-01-01")
    end = pd.Timestamp(f"{year + 1}-01-01")
    today = pd.Timestamp.utcnow().normalize().tz_localize(None)
    if end > today + pd.Timedelta(days=1):
        end = today + pd.Timedelta(days=1)
    print(f"\n=== v13 {start.date()} → {end.date()} weights={WEIGHTS} ===", flush=True)

    book_sims = {}
    sleeve_rows = []
    for book, w in WEIGHTS.items():
        sleeve_cap = CAPITAL * w
        sim, bh, n_mem = run_book(
            book, frames, sleeve_capital=sleeve_cap, start=start, end=end, cfg=cfg
        )
        book_sims[book] = sim
        m = metrics(sim.equity, sleeve_cap)
        mb = metrics(bh, sleeve_cap)
        modes = sim.mode.value_counts(normalize=True).to_dict() if len(sim.mode) else {}
        row = {
            "book": book,
            "weight": w,
            "n_members": n_mem,
            "total_return": m["total_return"],
            "max_drawdown": m["max_drawdown"],
            "sharpe": m["sharpe"],
            "bh_total_return": mb["total_return"],
            "mode_distribution": {str(k): float(v) for k, v in modes.items()},
            "n_trades": int(len(sim.trades)),
        }
        sleeve_rows.append(row)
        print(
            f"  {book:4} n={n_mem:3d} SG={m['total_return']*100:7.2f}% "
            f"BH={mb['total_return']*100:6.2f}% maxDD={m['max_drawdown']*100:6.2f}% "
            f"trades={row['n_trades']}",
            flush=True,
        )

    blended, panel = blend_structure_gate_books(book_sims, WEIGHTS, capital=CAPITAL)
    blended = blended.loc[start:end].dropna()
    panel = panel.reindex(blended.index).ffill()
    m_b = metrics(blended, CAPITAL)

    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    spy = frames["SPY"]
    eq_spy = (
        simulate_bench_bh(spy["open"], spy["close"], capital=CAPITAL, start=start, fees=fees)
        .reindex(blended.index)
        .ffill()
    )
    m_spy = metrics(eq_spy, CAPITAL)
    qqq = frames["QQQ"]
    eq_qqq = (
        simulate_bench_bh(qqq["open"], qqq["close"], capital=CAPITAL, start=start, fees=fees)
        .reindex(blended.index)
        .ffill()
    )
    m_qqq = metrics(eq_qqq, CAPITAL)
    etf_eq = []
    for book, w in WEIGHTS.items():
        bdf = frames[book]
        etf_eq.append(
            simulate_bench_bh(
                bdf["open"], bdf["close"], capital=CAPITAL * w, start=start, fees=fees
            )
        )
    static = pd.concat(etf_eq, axis=1).ffill().sum(axis=1).reindex(blended.index).ffill()
    m_static = metrics(static, CAPITAL)

    modes = pd.DataFrame({b: book_sims[b].mode for b in WEIGHTS}).reindex(blended.index).ffill()
    disagree = float((modes.nunique(axis=1) > 1).mean()) if len(modes) else float("nan")
    tag = f"{start.date()}_{min(blended.index.max(), end - pd.Timedelta(days=1)).date()}"
    OUT.mkdir(parents=True, exist_ok=True)
    blended.to_csv(OUT / f"equity_v13_{tag}.csv", header=["equity"])
    panel.to_csv(OUT / f"sleeves_{tag}.csv")
    eq_spy.to_csv(OUT / f"equity_spy_bh_{tag}.csv", header=["equity"])
    eq_qqq.to_csv(OUT / f"equity_qqq_bh_{tag}.csv", header=["equity"])

    vs_spy = (m_b["total_return"] - m_spy["total_return"]) * 100
    vs_qqq = (m_b["total_return"] - m_qqq["total_return"]) * 100
    vs_static = (m_b["total_return"] - m_static["total_return"]) * 100
    print(
        f"  BLEND SG={m_b['total_return']*100:7.2f}% maxDD={m_b['max_drawdown']*100:6.2f}% "
        f"sharpe={m_b['sharpe']:.2f} vsSPY={vs_spy:+.1f}pp vsQQQ={vs_qqq:+.1f}pp "
        f"vsStatic50/50={vs_static:+.1f}pp disagree={disagree*100:.1f}%",
        flush=True,
    )
    return {
        "year": year,
        "start": str(start.date()),
        "end": str(min(blended.index.max().date(), (end - pd.Timedelta(days=1)).date())),
        "blend": {
            "total_return": m_b["total_return"],
            "max_drawdown": m_b["max_drawdown"],
            "sharpe": m_b["sharpe"],
            "end_equity": m_b["end_equity"],
            "vs_spy_bh_pp": vs_spy,
            "vs_qqq_bh_pp": vs_qqq,
            "vs_static_etf_blend_pp": vs_static,
            "n_trades": int(sum(r["n_trades"] for r in sleeve_rows)),
            "mode_disagree_share": disagree,
        },
        "spy_bh": m_spy,
        "qqq_bh": m_qqq,
        "static_spy50_qqq50": m_static,
        "sleeves": sleeve_rows,
        "beat_spy": bool(m_b["total_return"] > m_spy["total_return"]),
        "beat_qqq": bool(m_b["total_return"] > m_qqq["total_return"]),
    }


def render_report(rows: list[dict]) -> str:
    lines = [
        "=== Structure Gate v13 年窗（SPY50 / QQQ50）===",
        "preset=StructureGateConfig.v13()  capital=$50k/年獨立  fees=Futu+3bps  next-open",
        "",
        f"{'\u5e74':<6} {'v13':>8} {'maxDD':>8} {'Sharpe':>7} {'SPY':>8} {'QQQ':>8} {'vsSPY':>8} {'vsQQQ':>8} {'\u52ddSPY':>6} {'\u52ddQQQ':>6}",
    ]
    wins_spy = wins_qqq = 0
    for r in rows:
        b = r["blend"]
        wins_spy += int(r["beat_spy"])
        wins_qqq += int(r["beat_qqq"])
        lines.append(
            f"{r['year']:<6} {b['total_return']*100:7.2f}% {b['max_drawdown']*100:7.2f}% "
            f"{b['sharpe']:7.2f} {r['spy_bh']['total_return']*100:7.2f}% "
            f"{r['qqq_bh']['total_return']*100:7.2f}% "
            f"{b['vs_spy_bh_pp']:+7.1f} {b['vs_qqq_bh_pp']:+7.1f} "
            f"{'Y' if r['beat_spy'] else 'N':>6} {'Y' if r['beat_qqq'] else 'N':>6}"
        )
    lines.append("")
    lines.append(f"勝 SPY：{wins_spy}/{len(rows)}　勝 QQQ：{wins_qqq}/{len(rows)}")
    lines.append("註：每年獨立起步，不是複利連走。2019 前需 2018 暖身 K 線。")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2019)
    ap.add_argument("--end-year", type=int, default=2026)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)

    want = sorted({"SPY", "QQQ"} | set(book_members("QQQ")) | set(book_members("SPY")))
    print(f"universe={len(want)} years={args.start_year}→{args.end_year}", flush=True)
    frames = load_universe(want)
    for b in WEIGHTS:
        if b not in frames:
            raise SystemExit(f"missing bench {b}")
        print(
            f"bench {b}: {frames[b].index.min().date()}→{frames[b].index.max().date()} n={len(frames[b])}",
            flush=True,
        )

    cfg = StructureGateConfig.v13()
    rows = []
    for year in range(args.start_year, args.end_year + 1):
        if pd.Timestamp(f"{year}-01-01") > pd.Timestamp.utcnow().normalize().tz_localize(None):
            break
        rows.append(run_year(year, frames, cfg))

    summary = {
        "ok": True,
        "preset": "v13",
        "weights": WEIGHTS,
        "capital_per_year": CAPITAL,
        "years": rows,
        "n_symbols_ok": len(frames),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float) + "\n")
    report = render_report(rows)
    (OUT / "report_zhTW.txt").write_text(report)
    print("\n" + report)
    print("wrote", OUT / "summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
