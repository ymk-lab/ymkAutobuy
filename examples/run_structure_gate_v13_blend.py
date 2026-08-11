#!/usr/bin/env python3
"""Structure Gate v13: independent SPY 50% / QQQ 50% sleeves.

Each book runs v13 knobs (hysteresis + risk override) on its own universe and
capital slice; portfolio equity is the sum.
"""

from __future__ import annotations

import json
import sys
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
    simulate_structure_gate,
)
from run_emerging_rs_wave_gates import UNIVERSE as QQQ_UNIVERSE, metrics  # type: ignore
from run_emerging_rs_wave_soxx import UNIVERSE as SEMI_UNIVERSE  # type: ignore
from run_structure_gate_bakeoff import soft_pass  # type: ignore

OUT = ROOT / "examples" / "data" / "structure_gate_v13_blend"
CAPITAL = 50_000.0
MIN_BARS = 220
WEIGHTS = dict(V13_BOOK_WEIGHTS)  # SPY 0.5 / QQQ 0.5

CACHE_DIRS = [
    # Local paper cache (Windows lean install usually only has this)
    ROOT / "examples/data/structure_gate_v13_paper/cache_ohlcv",
    ROOT / "examples/data/structure_gate_v11_paper/cache_ohlcv",
    ROOT / "examples/data/structure_gate_v8_paper/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_qqq_g1_longbridge/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_smh/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_soxx/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_spy/cache_ohlcv",
]


def _load_symbol(sym: str) -> pd.DataFrame | None:
    for cache in CACHE_DIRS:
        path = cache / f"{sym}.csv"
        if not path.is_file():
            continue
        try:
            raw = pd.read_csv(path, index_col=0, parse_dates=True)
            raw.columns = [str(c).lower() for c in raw.columns]
            df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            df = df[~df.index.duplicated(keep="last")].sort_index()
            if len(df) >= MIN_BARS:
                return df
        except Exception:
            continue
    return None


def load_many(symbols: list[str]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for i, s in enumerate(symbols, 1):
        df = _load_symbol(s)
        if df is not None:
            frames[s] = df
        if i == 1 or i % 80 == 0 or i == len(symbols):
            print(f"load [{i}/{len(symbols)}] ok={len(frames)}", flush=True)
    return frames


def spy_universe() -> list[str]:
    uf = ROOT / "examples/data/emerging_rs_wave_spy/universe.txt"
    if not uf.is_file():
        return []
    return [
        ln.strip().upper()
        for ln in uf.read_text().splitlines()
        if ln.strip() and not ln.startswith("#") and ln.strip().upper() != "SPY"
    ]


def book_members(book: str) -> list[str]:
    if book == "QQQ":
        return [s for s in QQQ_UNIVERSE if s != "QQQ"]
    if book == "SMH":
        return [s for s in SEMI_UNIVERSE if s != "SMH"]
    if book == "SPY":
        return spy_universe()
    raise ValueError(book)


def align_panel(
    frames: dict[str, pd.DataFrame], members: list[str], calendar: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.DataFrame]:
    opens = pd.DataFrame({s: frames[s]["open"].reindex(calendar) for s in members if s in frames})
    closes = pd.DataFrame({s: frames[s]["close"].reindex(calendar) for s in members if s in frames})
    keep = [c for c in closes.columns if closes[c].notna().sum() >= MIN_BARS]
    return opens[keep], closes[keep]


def run_book(
    book: str,
    frames: dict[str, pd.DataFrame],
    *,
    sleeve_capital: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cfg: StructureGateConfig,
):
    if book not in frames:
        raise SystemExit(f"missing bench {book}")
    bdf = frames[book].loc[:end]
    opens, closes = align_panel(frames, book_members(book), bdf.index)
    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    sim = simulate_structure_gate(
        opens,
        closes,
        bdf["open"],
        bdf["close"],
        capital=sleeve_capital,
        start=start,
        fees=fees,
        config=cfg,
        bench_volume=bdf["volume"] if "volume" in bdf.columns else None,
    )
    bh = simulate_bench_bh(
        bdf["open"], bdf["close"], capital=sleeve_capital, start=start, fees=fees
    ).reindex(sim.equity.index).ffill()
    return sim, bh, len(closes.columns)


def max_drawdown(eq: pd.Series) -> float:
    s = eq.dropna()
    if s.empty:
        return float("nan")
    peak = s.cummax()
    return float((s / peak - 1.0).min())


def run_window(start: pd.Timestamp, end: pd.Timestamp, frames: dict[str, pd.DataFrame]) -> dict:
    cfg = StructureGateConfig.v13()
    book_sims = {}
    sleeve_rows = []
    print(f"\n=== v13 blend {start.date()}→{end.date()} weights={WEIGHTS} ===", flush=True)
    for book, w in WEIGHTS.items():
        sleeve_cap = CAPITAL * w
        sim, bh, n_mem = run_book(
            book, frames, sleeve_capital=sleeve_cap, start=start, end=end, cfg=cfg
        )
        book_sims[book] = sim
        m = metrics(sim.equity, sleeve_cap)
        mb = metrics(bh, sleeve_cap)
        row = {
            "book": book,
            "weight": w,
            "sleeve_capital": sleeve_cap,
            "n_members": n_mem,
            "total_return": m["total_return"],
            "max_drawdown": m["max_drawdown"],
            "sharpe": m["sharpe"],
            "end_equity": m["end_equity"],
            "bh_total_return": mb["total_return"],
            "mode_distribution": sim.mode.value_counts(normalize=True).to_dict(),
            "n_trades": int(len(sim.trades)),
        }
        sleeve_rows.append(row)
        print(
            f"  {book:4} w={w:.0%} cap={sleeve_cap:,.0f} n={n_mem:3d} "
            f"SG={m['total_return']*100:7.2f}% BH={mb['total_return']*100:6.2f}% "
            f"maxDD={m['max_drawdown']*100:6.2f}% trades={row['n_trades']}",
            flush=True,
        )
        sim.equity.to_csv(OUT / f"equity_sleeve_{book}_{start.date()}_{end.date()}.csv", header=["equity"])

    blended, panel = blend_structure_gate_books(book_sims, WEIGHTS, capital=CAPITAL)
    # clip to eval window
    blended = blended.loc[start:end].dropna()
    panel = panel.reindex(blended.index).ffill()
    m_b = metrics(blended, CAPITAL)
    # SPY buy&hold on full capital as reference
    spy = frames["SPY"]
    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    eq_bh = simulate_bench_bh(
        spy["open"], spy["close"], capital=CAPITAL, start=start, fees=fees
    ).reindex(blended.index).ffill()
    m_bh = metrics(eq_bh, CAPITAL)
    # Equal-weight BH of three ETFs on full capital (risk ref)
    # Approximate: static ETF BH at sleeve weights
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

    gate = soft_pass(m_b["total_return"], m_bh["total_return"], m_static["total_return"])
    # Diversification: average pairwise correlation of sleeve daily returns
    rets = panel.pct_change().dropna(how="all")
    corr = rets.corr()
    # Mode disagreement: fraction of days where not all sleeves share same mode
    modes = pd.DataFrame({b: book_sims[b].mode for b in WEIGHTS})
    modes = modes.reindex(blended.index).ffill()
    disagree = float((modes.nunique(axis=1) > 1).mean()) if len(modes) else float("nan")

    out = {
        "start": str(start.date()),
        "end": str(end.date()),
        "weights": WEIGHTS,
        "capital": CAPITAL,
        "blend": {
            "total_return": m_b["total_return"],
            "max_drawdown": m_b["max_drawdown"],
            "sharpe": m_b["sharpe"],
            "end_equity": m_b["end_equity"],
            "vs_spy_bh_pp": (m_b["total_return"] - m_bh["total_return"]) * 100,
            "vs_static_etf_blend_pp": (m_b["total_return"] - m_static["total_return"]) * 100,
        },
        "spy_bh": m_bh,
        "static_etf_blend": m_static,
        "sleeves": sleeve_rows,
        "soft_pass": gate,
        "sleeve_return_corr": corr.to_dict(),
        "mode_disagree_share": disagree,
    }
    print(
        f"  BLEND   SG={m_b['total_return']*100:7.2f}% maxDD={m_b['max_drawdown']*100:6.2f}% "
        f"sharpe={m_b['sharpe']:.2f} vsSPY={out['blend']['vs_spy_bh_pp']:+.1f}pp "
        f"vsStaticETF={out['blend']['vs_static_etf_blend_pp']:+.1f}pp "
        f"mode_disagree={disagree*100:.1f}%",
        flush=True,
    )
    tag = f"{start.date()}_{end.date()}"
    blended.to_csv(OUT / f"equity_v13_blend_{tag}.csv", header=["equity"])
    panel.to_csv(OUT / f"equity_sleeves_{tag}.csv")
    eq_bh.to_csv(OUT / f"equity_spy_bh_{tag}.csv", header=["equity"])
    return out


def main() -> int:
    start = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2025-01-01")
    end = pd.Timestamp(sys.argv[2] if len(sys.argv) > 2 else "2026-08-07")
    # optional third arg "both" runs 2025 window + 2021-td
    mode = sys.argv[3] if len(sys.argv) > 3 else "one"
    OUT.mkdir(parents=True, exist_ok=True)

    want = sorted(
        set(WEIGHTS)
        | set(book_members("QQQ"))
        | set(book_members("SPY"))
    )
    present = [str(p) for p in CACHE_DIRS if p.is_dir()]
    print(f"cache_dirs_present={len(present)}", flush=True)
    for p in present[:6]:
        print(f"  {p}", flush=True)
    print(f"loading {len(want)} symbols for v13…", flush=True)
    frames = load_many(want)
    # Bootstrap benches via Yahoo if local paper cache somehow missing them.
    for b in WEIGHTS:
        if b in frames:
            continue
        try:
            import yfinance as yf

            raw = yf.download(b, start="2021-06-01", auto_adjust=True, progress=False, threads=False)
            if raw is None or len(raw) < MIN_BARS:
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = [str(c[0]).lower() for c in raw.columns]
            else:
                raw.columns = [str(c).lower() for c in raw.columns]
            df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            frames[b] = df[~df.index.duplicated(keep="last")].sort_index()
            paper_cache = ROOT / "examples/data/structure_gate_v13_paper/cache_ohlcv"
            paper_cache.mkdir(parents=True, exist_ok=True)
            frames[b].to_csv(paper_cache / f"{b}.csv")
            print(f"yf bootstrap {b} bars={len(frames[b])}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"yf bootstrap {b} failed: {exc}", flush=True)
    for b in WEIGHTS:
        if b not in frames:
            raise SystemExit(
                f"missing {b} — run paper signal once to fill "
                f"examples/data/structure_gate_v13_paper/cache_ohlcv"
            )

    windows = [(start, end)]
    if mode == "both":
        windows = [
            (pd.Timestamp("2025-01-01"), pd.Timestamp("2026-08-07")),
            (pd.Timestamp("2021-06-01"), pd.Timestamp("2026-08-07")),
        ]

    reports = []
    for a, b in windows:
        reports.append(run_window(a, b, frames))

    summary = {
        "ok": True,
        "preset": "v13_blend",
        "design": {
            "knobs": "StructureGateConfig.v13()",
            "weights": WEIGHTS,
            "execution": "independent simulate_structure_gate per book; sum equities",
            "intent": "v13 hysteresis + risk override; SPY50/QQQ50 (no SMH)",
        },
        "windows": reports,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float) + "\n")
    print("\nwrote", OUT / "summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
