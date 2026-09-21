#!/usr/bin/env python3
"""Structure Gate v13 calendar-year walk: 2019 → 2026.

Paper weights: SPY 50% / QQQ 50%. Config: StructureGateConfig.v13().
Each year is scored independently (capital reset to $50k on Jan 1).
Warm-up bars before the year stay in the panel so SMA / trail / ERS
lookbacks are valid; metrics only use the calendar year.

Survivorship: member lists are today's QQQ / SPY books (same as other
bakeoffs). Delisted names drop out; current mega-caps remain. Read
vs-SPY with that bias in mind.

Usage (from repo root)::

    python examples/run_structure_gate_v13_yearly_2019_2026.py
    python examples/run_structure_gate_v13_yearly_2019_2026.py --start 2019 --end 2026
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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
from run_structure_gate_v11_blend import (  # type: ignore
    book_members,
    run_book,
)

OUT = ROOT / "examples" / "data" / "structure_gate_v13_yearly_2019_2026"
CACHE = OUT / "cache_ohlcv"
CAPITAL = 50_000.0
MIN_BARS = 180
WEIGHTS = dict(V13_BOOK_WEIGHTS)  # SPY 0.50 / QQQ 0.50
YF_START = "2018-01-01"


def _normalize_yf(raw: pd.DataFrame) -> pd.DataFrame | None:
    if raw is None or len(raw) < 40:
        return None
    raw = raw.copy()
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [str(c[0]).lower() for c in raw.columns]
    else:
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
    print(f"cache present={len(symbols) - len(missing)} missing={len(missing)}", flush=True)
    if not missing:
        return
    chunk = 40
    for i in range(0, len(missing), chunk):
        batch = missing[i : i + chunk]
        print(f"yf {i + 1}-{i + len(batch)}/{len(missing)} {batch[:4]}…", flush=True)
        raw = None
        try:
            raw = yf.download(
                batch,
                start=YF_START,
                auto_adjust=True,
                progress=False,
                threads=True,
                group_by="ticker",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  batch fail: {exc}", flush=True)
        for sym in batch:
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
                        auto_adjust=True,
                        progress=False,
                        threads=False,
                    )
                    df = _normalize_yf(one)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {sym} fail: {exc}", flush=True)
                    continue
            if df is not None and len(df) >= MIN_BARS:
                df.to_csv(CACHE / f"{sym}.csv")
        time.sleep(0.35)


def load_cache(symbols: list[str]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols, 1):
        path = CACHE / f"{sym}.csv"
        if not path.is_file():
            continue
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
        if i == 1 or i % 100 == 0 or i == len(symbols):
            print(f"load [{i}/{len(symbols)}] ok={len(frames)}", flush=True)
    return frames


def year_windows(start_year: int, end_year: int):
    out = []
    today = pd.Timestamp.today().normalize()
    for y in range(start_year, end_year + 1):
        a = pd.Timestamp(f"{y}-01-01")
        b = pd.Timestamp(f"{y + 1}-01-01")
        if a >= today:
            break
        if b > today:
            b = today + pd.Timedelta(days=1)
        out.append((a, b))
    return out


def run_year(frames, start, end, cfg):
    book_sims = {}
    sleeve_rows = []
    for book, w in WEIGHTS.items():
        sleeve_cap = CAPITAL * w
        sim, bh, n_mem = run_book(
            book, frames, sleeve_capital=sleeve_cap, start=start, end=end, cfg=cfg
        )
        book_sims[book] = sim
        m = metrics(sim.equity.loc[start : end - pd.Timedelta(days=1)], sleeve_cap)
        mb = metrics(bh.loc[start : end - pd.Timedelta(days=1)], sleeve_cap)
        modes = sim.mode.loc[start : end - pd.Timedelta(days=1)]
        sleeve_rows.append(
            {
                "book": book,
                "weight": w,
                "n_members": n_mem,
                "total_return": m["total_return"],
                "max_drawdown": m["max_drawdown"],
                "sharpe": m["sharpe"],
                "bh_total_return": mb["total_return"],
                "mode_distribution": modes.value_counts(normalize=True).to_dict() if len(modes) else {},
                "n_trades": int(len(sim.trades)),
            }
        )

    blended, panel = blend_structure_gate_books(book_sims, WEIGHTS, capital=CAPITAL)
    blended = blended.loc[start : end - pd.Timedelta(days=1)].dropna()
    panel = panel.reindex(blended.index).ffill()
    m_b = metrics(blended, CAPITAL)

    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    spy = frames["SPY"]
    qqq = frames["QQQ"]
    eq_spy = simulate_bench_bh(spy["open"], spy["close"], capital=CAPITAL, start=start, fees=fees).reindex(blended.index).ffill()
    eq_qqq = simulate_bench_bh(qqq["open"], qqq["close"], capital=CAPITAL, start=start, fees=fees).reindex(blended.index).ffill()
    m_spy = metrics(eq_spy, CAPITAL)
    m_qqq = metrics(eq_qqq, CAPITAL)

    etf_eq = []
    for book, w in WEIGHTS.items():
        bdf = frames[book]
        etf_eq.append(simulate_bench_bh(bdf["open"], bdf["close"], capital=CAPITAL * w, start=start, fees=fees))
    static = pd.concat(etf_eq, axis=1).ffill().sum(axis=1).reindex(blended.index).ffill()
    m_static = metrics(static, CAPITAL)

    tag = f"{start.year}"
    blended.to_csv(OUT / f"equity_v13_{tag}.csv", header=["equity"])
    panel.to_csv(OUT / f"sleeves_{tag}.csv")
    eq_spy.to_csv(OUT / f"equity_spy_bh_{tag}.csv", header=["equity"])
    eq_qqq.to_csv(OUT / f"equity_qqq_bh_{tag}.csv", header=["equity"])

    return {
        "year": int(start.year),
        "start": str(start.date()),
        "end": str((end - pd.Timedelta(days=1)).date()),
        "v13": {
            "total_return": m_b["total_return"],
            "max_drawdown": m_b["max_drawdown"],
            "sharpe": m_b["sharpe"],
            "end_equity": m_b["end_equity"],
            "n_trades": int(sum(r["n_trades"] for r in sleeve_rows)),
            "vs_spy_pp": (m_b["total_return"] - m_spy["total_return"]) * 100,
            "vs_qqq_pp": (m_b["total_return"] - m_qqq["total_return"]) * 100,
            "vs_static_pp": (m_b["total_return"] - m_static["total_return"]) * 100,
        },
        "spy_bh": m_spy,
        "qqq_bh": m_qqq,
        "static_5050": m_static,
        "sleeves": sleeve_rows,
    }


def render_report(rows):
    lines = [
        "=== Structure Gate v13 yearly 2019-2026 ===",
        "preset=StructureGateConfig.v13()  weights=SPY50/QQQ50  capital=$50k",
        "exec=next-open + Futu fees + 3bps  members=current book (survivorship)",
        "",
        f"{'year':<6}{'v13':>10}{'SPY':>10}{'QQQ':>10}{'vsSPY':>10}{'vsQQQ':>10}{'maxDD':>10}{'trd':>6}",
    ]
    wins_spy = 0
    for r in rows:
        v = r["v13"]
        spy = r["spy_bh"]["total_return"]
        qqq = r["qqq_bh"]["total_return"]
        if v["vs_spy_pp"] > 0:
            wins_spy += 1
        lines.append(
            f"{r['year']:<6}{v['total_return']*100:9.2f}%{spy*100:9.2f}%{qqq*100:9.2f}%{v['vs_spy_pp']:+9.1f}pp{v['vs_qqq_pp']:+9.1f}pp{v['max_drawdown']*100:9.2f}%{v['n_trades']:6d}"
        )
    lines.append("")
    lines.append(f"years vs SPY win: {wins_spy}/{len(rows)}")
    lines.append("=== END ===")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=2019)
    ap.add_argument("--end", type=int, default=2026)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    cfg = StructureGateConfig.v13()
    want = sorted({"SPY", "QQQ"} | set(book_members("QQQ")) | set(book_members("SPY")))
    print(f"symbols={len(want)} years={args.start}\u2192{args.end}", flush=True)
    bootstrap_cache(want)
    frames = load_cache(want)
    for b in WEIGHTS:
        if b not in frames:
            raise SystemExit(f"missing bench {b} after Yahoo bootstrap")
        print(f"bench {b}: {frames[b].index.min().date()}\u2192{frames[b].index.max().date()} n={len(frames[b])}", flush=True)

    rows = []
    for a, b in year_windows(args.start, args.end):
        print(f"\n=== v13 {a.year} ===", flush=True)
        try:
            rep = run_year(frames, a, b, cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {a.year}: {exc}", flush=True)
            rows.append({"year": int(a.year), "error": str(exc)})
            continue
        v = rep["v13"]
        print(
            f"  v13={v['total_return']*100:+.2f}% maxDD={v['max_drawdown']*100:.2f}% "
            f"vsSPY={v['vs_spy_pp']:+.1f}pp vsQQQ={v['vs_qqq_pp']:+.1f}pp trades={v['n_trades']}",
            flush=True,
        )
        rows.append(rep)

    summary = {
        "ok": True,
        "preset": "v13",
        "weights": WEIGHTS,
        "capital": CAPITAL,
        "note": "calendar years, capital reset each Jan 1; current-member survivorship",
        "years": rows,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float) + "\n")
    report = render_report([r for r in rows if "v13" in r])
    (OUT / "report.txt").write_text(report + "\n")
    (OUT / "report_zhTW.txt").write_text(report + "\n")
    print("\n" + report)
    print("wrote", OUT / "summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
