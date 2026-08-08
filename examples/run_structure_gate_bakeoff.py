#!/usr/bin/env python3
"""Bake-Off: same Structure Gate on QQQ / SMH / SOXX / SPY (ticker-agnostic)."""

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
from qresearch.strategy.emerging_rs_wave import EmergingRSWaveBook
from qresearch.strategy.regime_playbook import simulate_bench_bh, simulate_cash
from qresearch.strategy.structure_gate import StructureGateConfig, simulate_structure_gate
from run_emerging_rs_wave_gates import (  # type: ignore
    CAPITAL,
    START,
    UNIVERSE as QQQ_UNIVERSE,
    metrics,
    simulate_book,
)
from run_emerging_rs_wave_soxx import UNIVERSE as SEMI_UNIVERSE  # type: ignore

OUT = ROOT / "examples" / "data" / "structure_gate_bakeoff"
END = pd.Timestamp("2026-08-07")
MIN_BARS = 220
# Soft pass: beat the worse baseline, and trail the better one by at most this many pp.
SOFT_MAX_GAP_PP = 35.0

BOOKS = {
    "QQQ": {
        "bench": "QQQ",
        "universe": QQQ_UNIVERSE,
        "caches": [
            ROOT / "examples" / "data" / "emerging_rs_wave_qqq_g1_longbridge" / "cache_ohlcv",
            Path("/opt/qresearch/examples/data/emerging_rs_wave_qqq_g1_longbridge/cache_ohlcv"),
        ],
    },
    "SMH": {
        "bench": "SMH",
        "universe": SEMI_UNIVERSE,
        "caches": [
            ROOT / "examples" / "data" / "emerging_rs_wave_smh" / "cache_ohlcv",
        ],
    },
    "SOXX": {
        "bench": "SOXX",
        "universe": SEMI_UNIVERSE,
        "caches": [
            ROOT / "examples" / "data" / "emerging_rs_wave_soxx" / "cache_ohlcv",
        ],
    },
    "SPY": {
        "bench": "SPY",
        "universe": None,  # filled from universe.txt beside cache
        "universe_file": ROOT
        / "examples"
        / "data"
        / "emerging_rs_wave_spy"
        / "universe.txt",
        "caches": [
            ROOT / "examples" / "data" / "emerging_rs_wave_spy" / "cache_ohlcv",
        ],
    },
}


def _load(path: Path) -> pd.DataFrame | None:
    if not path.is_file() or path.stat().st_size < 64:
        return None
    raw = pd.read_csv(path, index_col=0, parse_dates=True)
    raw.columns = [str(c).lower() for c in raw.columns]
    try:
        df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
    except ValueError:
        return None
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[~df.index.duplicated(keep="last")].sort_index()


def _universe_for(book: str) -> list[str]:
    spec = BOOKS[book]
    uni = spec.get("universe")
    if uni:
        return list(uni)
    uf = spec.get("universe_file")
    if uf is not None and Path(uf).is_file():
        return [
            ln.strip()
            for ln in Path(uf).read_text().splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
    raise SystemExit(f"{book}: no universe")


def load_panel(book: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Path]:
    spec = BOOKS[book]
    cache = next((p for p in spec["caches"] if p.is_dir()), None)
    if cache is None:
        raise SystemExit(f"{book}: cache not found")
    bench_sym = spec["bench"]
    bench = _load(cache / f"{bench_sym}.csv")
    if bench is None:
        raise SystemExit(f"{bench_sym} missing in {cache}")
    frames = {}
    for sym in _universe_for(book):
        if sym == bench_sym:
            continue
        df = _load(cache / f"{sym}.csv")
        if df is not None and len(df) >= MIN_BARS:
            frames[sym] = df.loc[:END]
    bench = bench.loc[:END]
    idx = bench.index
    closes = pd.DataFrame({s: frames[s]["close"].reindex(idx) for s in frames})
    opens = pd.DataFrame({s: frames[s]["open"].reindex(idx) for s in frames})
    keep = [c for c in closes.columns if closes[c].notna().sum() >= MIN_BARS]
    print(f"{book}: cache={cache} usable={len(keep)}")
    return bench, opens[keep], closes[keep], cache


def soft_pass(sw: float, bh: float, ers: float, max_gap_pp: float = SOFT_MAX_GAP_PP) -> dict:
    better = max(bh, ers)
    worse = min(bh, ers)
    gap_pp = (better - sw) * 100
    beat_worse = sw > worse
    within = gap_pp <= max_gap_pp
    return {
        "soft_pass": bool(beat_worse and within),
        "beat_worse_baseline": beat_worse,
        "within_gap_of_better": within,
        "gap_vs_better_pp": gap_pp,
        "hard_pass_beat_both": bool(sw > bh and sw > ers),
        "max_gap_pp": max_gap_pp,
    }


def run_book(book: str, fees: FutuUsEquityFees, cfg: StructureGateConfig) -> dict:
    bench, opens, closes, cache = load_panel(book)
    out_dir = OUT / book.lower()
    out_dir.mkdir(parents=True, exist_ok=True)

    sw = simulate_structure_gate(
        opens,
        closes,
        bench["open"],
        bench["close"],
        capital=CAPITAL,
        start=START,
        fees=fees,
        config=cfg,
    )
    m_sw = metrics(sw.equity, CAPITAL)

    ers_book = EmergingRSWaveBook(gate="G1")
    decision, _ = ers_book.generate_weights(closes, bench["close"])
    win = sw.equity.index
    eq_ers, _ = simulate_book(
        opens.loc[win], closes.loc[win], decision.loc[win], CAPITAL, fees
    )
    m_ers = metrics(eq_ers, CAPITAL)

    eq_bh = simulate_bench_bh(
        bench["open"], bench["close"], capital=CAPITAL, start=START, fees=fees
    ).reindex(win).ffill()
    m_bh = metrics(eq_bh, CAPITAL)
    m_cash = metrics(simulate_cash(capital=CAPITAL, index=win), CAPITAL)

    dist = sw.mode.value_counts(normalize=True).sort_values(ascending=False)
    gate = soft_pass(m_sw["total_return"], m_bh["total_return"], m_ers["total_return"])

    sticky = sw.meta["sticky"].fillna(0) > 0.5
    sticky_cov = float(sticky.mean()) if len(sticky) else 0.0
    if sticky.any():
        sticky_modes = sw.mode.loc[sticky]
        bench_share = float((sticky_modes == "bench").mean())
        stock_leak = float(sticky_modes.isin(["ers", "strong"]).mean())
        cash_share = float((sticky_modes == "cash").mean())
    else:
        bench_share, stock_leak, cash_share = 0.0, 0.0, 0.0
    thrust = sw.meta["thrust"].fillna(0) > 0.5
    thrust_cov = float(thrust.mean()) if len(thrust) else 0.0
    thrust_bench = float((sw.mode.loc[thrust] == "bench").mean()) if thrust.any() else 0.0
    audit = {
        "sticky_coverage": sticky_cov,
        "sticky_bench_share": bench_share,
        "sticky_stock_sleeve_leak": stock_leak,
        "sticky_cash_share": cash_share,
        "thrust_coverage": thrust_cov,
        "thrust_bench_share": thrust_bench,
        "theme_bh_gap_ok_20pp": bool(
            (m_bh["total_return"] - m_sw["total_return"]) * 100 <= 20.0
        ),
    }

    rows = [
        {"name": "structure_gate", **m_sw},
        {"name": "pure_ers_g1", **m_ers},
        {"name": "bench_bh", **m_bh},
        {"name": "always_cash", **m_cash},
    ]
    summary = pd.DataFrame(rows)
    summary["vs_bh_pp"] = (summary["total_return"] - m_bh["total_return"]) * 100
    summary["vs_ers_pp"] = (summary["total_return"] - m_ers["total_return"]) * 100

    sw.equity.to_csv(out_dir / "equity_structure_gate.csv", header=True)
    eq_ers.to_csv(out_dir / "equity_pure_ers_g1.csv", header=True)
    eq_bh.to_csv(out_dir / "equity_bench_bh.csv", header=True)
    sw.mode.to_csv(out_dir / "modes.csv", header=True)
    sw.meta.to_csv(out_dir / "structure_meta.csv")
    if len(sw.trades):
        sw.trades.to_csv(out_dir / "trades.csv", index=False)
    summary.to_csv(out_dir / "summary.csv", index=False)

    report = {
        "book": book,
        "benchmark": BOOKS[book]["bench"],
        "universe_n": int(closes.shape[1]),
        "cache": str(cache),
        "window": [str(START.date()), str(win.max().date())],
        "capital_usd": CAPITAL,
        "same_rule": True,
        "structure_gate": m_sw,
        "pure_ers_g1": m_ers,
        "bench_bh": m_bh,
        "mode_distribution": dist.to_dict(),
        "sticky_audit": audit,
        "criteria": {
            "hard": "beat bench_bh AND pure_ers_g1",
            "soft": f"beat worse baseline AND trail better by ≤{SOFT_MAX_GAP_PP:.0f}pp",
            "theme_track": "vs bench_bh gap ≤20pp (theme book aspirational)",
        },
        **gate,
        "vs_bh_pp": (m_sw["total_return"] - m_bh["total_return"]) * 100,
        "vs_ers_pp": (m_sw["total_return"] - m_ers["total_return"]) * 100,
    }
    (out_dir / "bakeoff.json").write_text(json.dumps(report, indent=2, default=float) + "\n")

    print(f"\n=== STRUCTURE GATE — {book} ===")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("mode mix:", (dist * 100).round(1).astype(str).add("%").to_dict())
    print(
        "audit:",
        f"sticky_cov={audit['sticky_coverage']*100:.1f}%",
        f"bench_in_sticky={audit['sticky_bench_share']*100:.1f}%",
        f"stock_leak={audit['sticky_stock_sleeve_leak']*100:.1f}%",
        f"cash_in_sticky={audit['sticky_cash_share']*100:.1f}%",
        f"| thrust_cov={audit['thrust_coverage']*100:.1f}%",
        f"bench_in_thrust={audit['thrust_bench_share']*100:.1f}%",
    )
    print(
        f"HARD={gate['hard_pass_beat_both']} SOFT={gate['soft_pass']} "
        f"| gap_vs_better={gate['gap_vs_better_pp']:+.1f}pp "
        f"| vs BH {report['vs_bh_pp']:+.1f}pp vs ERS {report['vs_ers_pp']:+.1f}pp"
    )
    return report


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fees = FutuUsEquityFees(slippage_bps=3.0)
    cfg = StructureGateConfig()
    books = [a.strip().upper() for a in sys.argv[1:]] or ["QQQ", "SMH"]
    reports = [run_book(b, fees, cfg) for b in books]

    both_soft = all(r["soft_pass"] for r in reports)
    both_hard = all(r["hard_pass_beat_both"] for r in reports)
    combined = {
        "rule": "structure_gate_v6",
        "ticker_agnostic": True,
        "soft_max_gap_pp": SOFT_MAX_GAP_PP,
        "both_soft_pass": both_soft,
        "both_hard_pass": both_hard,
        "books": {r["book"]: r for r in reports},
        "config": {
            "sticky_enter_trail": cfg.sticky_enter_trail,
            "sticky_enter_confirm": cfg.sticky_enter_confirm,
            "sticky_exit_trail": cfg.sticky_exit_trail,
            "sticky_exit_confirm": cfg.sticky_exit_confirm,
            "sticky_exit_on_below50": cfg.sticky_exit_on_below50,
            "sticky_breadth_max": cfg.sticky_breadth_max,
            "sticky_forbid_stock_sleeves": cfg.sticky_forbid_stock_sleeves,
            "harsh_defense_dd": cfg.harsh_defense_dd,
            "thrust_ret5_min": cfg.thrust_ret5_min,
            "thrust_ret10_min": cfg.thrust_ret10_min,
            "thrust_bounce20_min": cfg.thrust_bounce20_min,
            "thrust_ret20_min": cfg.thrust_ret20_min,
            "thrust_overrides_dd_harsh": cfg.thrust_overrides_dd_harsh,
            "thrust_force_bench": cfg.thrust_force_bench,
        },
        "naming": {
            "modes": ["cash", "ers", "strong", "bench"],
            "locus": ["stock_led", "index_lean", "neutral"],
            "sleeves": ["sticky", "thrust", "crowded"],
            "defense": ["mild", "harsh"],
        },
        "note": (
            "v6 unified names: modes cash/ers/strong/bench; sleeves sticky/thrust; "
            "thrust overrides lagging dd60 harsh and forces bench while ripping."
        ),
    }
    (OUT / "bakeoff_combined.json").write_text(
        json.dumps(combined, indent=2, default=float) + "\n"
    )
    print("\n=== COMBINED ===")
    print(f"both_soft_pass={both_soft} both_hard_pass={both_hard}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
