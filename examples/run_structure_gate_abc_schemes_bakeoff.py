#!/usr/bin/env python3
"""Bakeoff: v11/v13 × schemes A/B/C × years 2020/2022/2024/2026.

Schemes (from risk discussion — replace SMH third sleeve):
  A 穩健: SPY 50% / QQQ 30% / DIA 20%
  B 均衡: SPY 40% / QQQ 30% / IWM 30%
  C 抗科技: SPY 40% / QQQ 25% / XLF 35%   # XLF (have universe; no XLI list)

Data: Yahoo bootstrap into dedicated cache (2019-01 → 2026-08).
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

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.data.loader import validate_ohlcv
from qresearch.strategy.regime_playbook import simulate_bench_bh
from qresearch.strategy.structure_gate import (
    StructureGateConfig,
    blend_structure_gate_books,
    simulate_structure_gate,
)
from run_emerging_rs_wave_gates import UNIVERSE as QQQ_UNIVERSE, metrics  # type: ignore
from run_structure_gate_bakeoff import soft_pass  # type: ignore

OUT = ROOT / "examples" / "data" / "structure_gate_abc_schemes"
CACHE = OUT / "cache_ohlcv_2019_2026"
YF_START = "2019-01-01"
YF_END = "2026-08-08"
MIN_BARS = 220
CAPITAL = 50_000.0

SCHEMES: dict[str, dict[str, float]] = {
    "A": {"SPY": 0.50, "QQQ": 0.30, "DIA": 0.20},  # 穩健
    "B": {"SPY": 0.40, "QQQ": 0.30, "IWM": 0.30},  # 均衡
    "C": {"SPY": 0.40, "QQQ": 0.25, "XLF": 0.35},  # 抗科技（XLF）
}

WINDOWS = [
    (pd.Timestamp("2020-01-01"), pd.Timestamp("2021-01-01")),
    (pd.Timestamp("2022-01-01"), pd.Timestamp("2023-01-01")),
    (pd.Timestamp("2024-01-01"), pd.Timestamp("2025-01-01")),
    (pd.Timestamp("2026-01-01"), pd.Timestamp("2026-08-07")),
]

VARIANTS = {
    "v11": StructureGateConfig.v11(),
    "v13": StructureGateConfig.v13(),
}


def _read_universe(path: Path, *, exclude: set[str] | None = None) -> list[str]:
    ex = {x.upper() for x in (exclude or set())}
    if not path.is_file():
        return []
    out = []
    for ln in path.read_text().splitlines():
        s = ln.strip().upper()
        if not s or s.startswith("#") or s in ex:
            continue
        out.append(s)
    return out


def book_members(book: str) -> list[str]:
    if book == "QQQ":
        return [s for s in QQQ_UNIVERSE if s != "QQQ"]
    if book == "SPY":
        return _read_universe(
            ROOT / "examples/data/emerging_rs_wave_spy/universe.txt", exclude={"SPY"}
        )
    if book == "DIA":
        return _read_universe(
            ROOT / "examples/data/emerging_rs_wave_dia/universe.txt", exclude={"DIA"}
        )
    if book == "IWM":
        # Cap to keep Yahoo bootstrap tractable; prefer names already cached.
        full = _read_universe(
            ROOT / "examples/data/emerging_rs_wave_iwm/universe.txt", exclude={"IWM"}
        )
        return full[:250]
    if book == "XLF":
        return _read_universe(
            ROOT / "examples/data/emerging_rs_wave_xlf/universe.txt", exclude={"XLF"}
        )
    raise ValueError(book)


def _normalize_yf(raw: pd.DataFrame) -> pd.DataFrame | None:
    if raw is None or len(raw) == 0:
        return None
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    need = ["open", "high", "low", "close", "volume"]
    if any(c not in df.columns for c in need):
        return None
    try:
        # Soften strict OHLC: clip high/low to envelope of open/close.
        o, h, l, c = df["open"], df["high"], df["low"], df["close"]
        df["high"] = pd.concat([h, o, c], axis=1).max(axis=1)
        df["low"] = pd.concat([l, o, c], axis=1).min(axis=1)
        out = validate_ohlcv(df[need].dropna())
    except Exception:
        return None
    out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out if len(out) >= MIN_BARS else None


def _cache_ok(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        raw = pd.read_csv(path, index_col=0, parse_dates=True)
        if len(raw) < MIN_BARS:
            return False
        idx = pd.to_datetime(raw.index)
        return idx.min() <= pd.Timestamp("2019-06-01") and idx.max() >= pd.Timestamp(
            "2026-06-01"
        )
    except Exception:
        return False


def bootstrap(symbols: list[str]) -> None:
    import yfinance as yf

    CACHE.mkdir(parents=True, exist_ok=True)
    # Seed from older stress cache when usable (then still may need extend).
    old = ROOT / "examples/data/structure_gate_v13_vs_v11/cache_ohlcv_2019"
    missing = []
    for s in symbols:
        dest = CACHE / f"{s}.csv"
        if _cache_ok(dest):
            continue
        # try copy+extend later via redownload if short
        src = old / f"{s}.csv"
        if src.is_file() and not dest.is_file():
            try:
                dest.write_bytes(src.read_bytes())
            except Exception:
                pass
        if not _cache_ok(dest):
            missing.append(s)

    print(f"bootstrap need={len(missing)} / {len(symbols)}", flush=True)
    chunk = 30
    for i in range(0, len(missing), chunk):
        batch = missing[i : i + chunk]
        print(f"yf {i+1}-{i+len(batch)}/{len(missing)} {batch[:4]}…", flush=True)
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
            print(f"  batch err {exc}", flush=True)
            raw = None
        for sym in batch:
            df = None
            if raw is not None and len(batch) > 1:
                try:
                    if isinstance(raw.columns, pd.MultiIndex) and sym in set(
                        raw.columns.get_level_values(0)
                    ):
                        df = _normalize_yf(raw[sym].dropna(how="all"))
                except Exception:
                    df = None
            elif raw is not None:
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
                except Exception:
                    df = None
            if df is not None:
                df.to_csv(CACHE / f"{sym}.csv")
            else:
                print(f"  skip {sym}", flush=True)
        time.sleep(0.35)


def load_frames(symbols: list[str]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols, 1):
        path = CACHE / f"{sym}.csv"
        if not path.is_file():
            continue
        try:
            raw = pd.read_csv(path, index_col=0, parse_dates=True)
            raw.columns = [str(c).lower() for c in raw.columns]
            # same soft OHLC fix
            o, h, l, c = raw["open"], raw["high"], raw["low"], raw["close"]
            raw["high"] = pd.concat([h, o, c], axis=1).max(axis=1)
            raw["low"] = pd.concat([l, o, c], axis=1).min(axis=1)
            df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            df = df[~df.index.duplicated(keep="last")].sort_index()
            if len(df) >= MIN_BARS:
                frames[sym] = df
        except Exception:
            continue
        if i == 1 or i % 100 == 0 or i == len(symbols):
            print(f"load [{i}/{len(symbols)}] ok={len(frames)}", flush=True)
    return frames


def align_panel(
    frames: dict[str, pd.DataFrame], members: list[str], calendar: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.DataFrame]:
    opens = pd.DataFrame(
        {s: frames[s]["open"].reindex(calendar) for s in members if s in frames}
    )
    closes = pd.DataFrame(
        {s: frames[s]["close"].reindex(calendar) for s in members if s in frames}
    )
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
    return sim, len(closes.columns)


def run_blend(
    frames: dict[str, pd.DataFrame],
    cfg: StructureGateConfig,
    weights: dict[str, float],
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    label: str,
) -> dict:
    book_sims = {}
    sleeves = []
    for book, w in weights.items():
        if book not in frames:
            raise SystemExit(f"missing bench {book}")
        cap = CAPITAL * w
        sim, n_mem = run_book(
            book, frames, sleeve_capital=cap, start=start, end=end, cfg=cfg
        )
        book_sims[book] = sim
        m = metrics(sim.equity, cap)
        # sleeve ETF BH
        bdf = frames[book]
        fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
        bh = simulate_bench_bh(
            bdf["open"], bdf["close"], capital=cap, start=start, fees=fees
        ).reindex(sim.equity.index).ffill()
        mb = metrics(bh, cap)
        sleeves.append(
            {
                "book": book,
                "weight": w,
                "n_members": n_mem,
                "total_return": m["total_return"],
                "max_drawdown": m["max_drawdown"],
                "sharpe": m["sharpe"],
                "bh_total_return": mb["total_return"],
                "mode_distribution": sim.mode.value_counts(normalize=True).to_dict(),
                "n_trades": int(len(sim.trades)),
            }
        )

    blended, _panel = blend_structure_gate_books(book_sims, weights, capital=CAPITAL)
    blended = blended.loc[start:end].dropna()
    m_b = metrics(blended, CAPITAL)

    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    spy = frames["SPY"]
    eq_bh = simulate_bench_bh(
        spy["open"], spy["close"], capital=CAPITAL, start=start, fees=fees
    ).reindex(blended.index).ffill()
    m_bh = metrics(eq_bh, CAPITAL)

    etf_eq = []
    for book, w in weights.items():
        bdf = frames[book]
        etf_eq.append(
            simulate_bench_bh(
                bdf["open"], bdf["close"], capital=CAPITAL * w, start=start, fees=fees
            )
        )
    static = pd.concat(etf_eq, axis=1).ffill().sum(axis=1).reindex(blended.index).ffill()
    m_static = metrics(static, CAPITAL)
    gate = soft_pass(m_b["total_return"], m_bh["total_return"], m_static["total_return"])

    tag = f"{label}_{start.date()}_{end.date()}"
    blended.to_csv(OUT / f"equity_{tag}.csv", header=["equity"])

    return {
        "label": label,
        "start": str(start.date()),
        "end": str(end.date()),
        "weights": weights,
        "blend": {
            "total_return": m_b["total_return"],
            "max_drawdown": m_b["max_drawdown"],
            "sharpe": m_b["sharpe"],
            "end_equity": m_b["end_equity"],
            "vs_spy_bh_pp": (m_b["total_return"] - m_bh["total_return"]) * 100,
            "vs_static_etf_pp": (m_b["total_return"] - m_static["total_return"]) * 100,
            "n_trades": int(sum(s["n_trades"] for s in sleeves)),
        },
        "spy_bh": m_bh,
        "static_etf": m_static,
        "soft_pass": gate,
        "sleeves": sleeves,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    books_needed = sorted({b for w in SCHEMES.values() for b in w})
    want = set(books_needed)
    for b in books_needed:
        want |= set(book_members(b))
    want_list = sorted(want)
    print(f"symbols={len(want_list)} books={books_needed}", flush=True)
    print(f"IWM members capped={len(book_members('IWM'))}", flush=True)

    bootstrap(want_list)
    frames = load_frames(want_list)
    for b in books_needed:
        if b not in frames:
            raise SystemExit(f"missing {b}")
        print(
            f"bench {b}: {frames[b].index.min().date()}→{frames[b].index.max().date()} n={len(frames[b])}",
            flush=True,
        )

    rows = []
    reports = []
    for scheme, weights in SCHEMES.items():
        for vname, cfg in VARIANTS.items():
            for a, b in WINDOWS:
                label = f"{scheme}_{vname}"
                print(f"\n=== {label} {a.date()}→{b.date()} {weights} ===", flush=True)
                rep = run_blend(frames, cfg, weights, a, b, label=label)
                reports.append(rep)
                bl = rep["blend"]
                row = {
                    "scheme": scheme,
                    "variant": vname,
                    "start": rep["start"],
                    "end": rep["end"],
                    "weights": weights,
                    "ret": bl["total_return"],
                    "maxdd": bl["max_drawdown"],
                    "sharpe": bl["sharpe"],
                    "vs_spy_pp": bl["vs_spy_bh_pp"],
                    "vs_static_pp": bl["vs_static_etf_pp"],
                    "trades": bl["n_trades"],
                    "spy_bh": rep["spy_bh"]["total_return"],
                    "static_etf": rep["static_etf"]["total_return"],
                    "hard_pass": rep["soft_pass"].get("hard_pass_beat_both"),
                    "soft_pass": rep["soft_pass"].get("soft_pass"),
                }
                rows.append(row)
                print(
                    f"  ret={bl['total_return']*100:7.2f}% maxDD={bl['max_drawdown']*100:6.2f}% "
                    f"sharpe={bl['sharpe']:.2f} vsSPY={bl['vs_spy_bh_pp']:+.1f}pp "
                    f"vsStatic={bl['vs_static_etf_pp']:+.1f}pp trades={bl['n_trades']}",
                    flush=True,
                )

    summary = {
        "ok": True,
        "schemes": SCHEMES,
        "scheme_notes": {
            "A": "穩健 SPY50/QQQ30/DIA20",
            "B": "均衡 SPY40/QQQ30/IWM30 (IWM universe capped 250)",
            "C": "抗科技 SPY40/QQQ25/XLF35",
        },
        "windows": [(str(a.date()), str(b.date())) for a, b in WINDOWS],
        "rows": rows,
        "reports": reports,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float) + "\n")

    # Pretty tables
    df = pd.DataFrame(rows)
    lines = [
        "=== Structure Gate ABC schemes × v11/v13 × 2020/2022/2024/2026 ===",
        "A: SPY50/QQQ30/DIA20 | B: SPY40/QQQ30/IWM30 | C: SPY40/QQQ25/XLF35",
        "costs: Futu+3bps | exec: next-open | capital: $50k",
        "",
    ]
    for start, end in [(str(a.date()), str(b.date())) for a, b in WINDOWS]:
        sub = df[df.start == start].copy()
        lines.append(f"## {start} → {end}")
        if len(sub):
            spy = float(sub.iloc[0]["spy_bh"])
            lines.append(f"SPY B&H (ref): {spy*100:+.2f}%")
        lines.append(
            f"{'scheme':6} {'var':4} {'ret%':>8} {'maxDD%':>8} {'sharpe':>7} "
            f"{'vsSPY':>8} {'vsStatic':>9} {'trades':>7} {'hard':>5}"
        )
        for _, r in sub.sort_values(["scheme", "variant"]).iterrows():
            lines.append(
                f"{r['scheme']:6} {r['variant']:4} {r['ret']*100:8.2f} {r['maxdd']*100:8.2f} "
                f"{r['sharpe']:7.2f} {r['vs_spy_pp']:+8.1f} {r['vs_static_pp']:+9.1f} "
                f"{int(r['trades']):7d} {str(bool(r['hard_pass'])):5}"
            )
        # best by ret in window
        if len(sub):
            best = sub.loc[sub["ret"].idxmax()]
            lines.append(
                f"best_ret: {best['scheme']}/{best['variant']} "
                f"{best['ret']*100:+.2f}% (maxDD {best['maxdd']*100:.2f}%)"
            )
        lines.append("")

    # Cross-year average rank by scheme/variant
    lines.append("## Average ret% across 4 windows")
    g = df.groupby(["scheme", "variant"])["ret"].mean().sort_values(ascending=False)
    for (sch, var), val in g.items():
        avg_dd = df[(df.scheme == sch) & (df.variant == var)]["maxdd"].mean()
        lines.append(f"  {sch}/{var}: avg_ret={val*100:+.2f}% avg_maxDD={avg_dd*100:.2f}%")

    report = "\n".join(lines)
    (OUT / "compare_report.txt").write_text(report + "\n")
    (OUT / "compare_report_zhTW.txt").write_text(report + "\n")
    print("\n" + report)
    print("wrote", OUT / "summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
