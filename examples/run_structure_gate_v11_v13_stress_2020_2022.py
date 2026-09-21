#!/usr/bin/env python3
"""Out-of-sample stress: Structure Gate v11 vs v13 on 2020 and 2022.

Local caches often start mid-2021; this script bootstraps Yahoo OHLCV from
2019-01-01 into a dedicated cache, then runs the SPY/QQQ/SMH blend bakeoff.
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

from qresearch.data.loader import validate_ohlcv
from qresearch.strategy.structure_gate import StructureGateConfig
from run_structure_gate_v11_blend import (  # type: ignore
    WEIGHTS,
    book_members,
)
from run_structure_gate_v13_vs_v11 import run_blend  # type: ignore

OUT = ROOT / "examples" / "data" / "structure_gate_v13_vs_v11"
CACHE = OUT / "cache_ohlcv_2019"
YF_START = "2019-01-01"
YF_END = "2023-06-01"
MIN_BARS = 220

WINDOWS = [
    (pd.Timestamp("2020-01-01"), pd.Timestamp("2021-01-01")),
    (pd.Timestamp("2022-01-01"), pd.Timestamp("2023-01-01")),
]


def _normalize_yf(raw: pd.DataFrame) -> pd.DataFrame | None:
    if raw is None or len(raw) < MIN_BARS:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        # single-ticker download → level0 is OHLCV
        raw = raw.copy()
        raw.columns = [str(c[0]).lower() for c in raw.columns]
    else:
        raw = raw.copy()
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
    print(f"cache={CACHE} present={len(symbols)-len(missing)} missing={len(missing)}", flush=True)
    if not missing:
        return

    # Batch download in chunks for speed; fall back per-symbol on failure.
    chunk = 40
    for i in range(0, len(missing), chunk):
        batch = missing[i : i + chunk]
        print(f"yf batch {i+1}-{i+len(batch)} / {len(missing)}: {batch[:5]}…", flush=True)
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
            print(f"  batch failed: {exc}", flush=True)
            raw = None

        for sym in batch:
            path = CACHE / f"{sym}.csv"
            df = None
            if raw is not None and len(batch) > 1:
                try:
                    if isinstance(raw.columns, pd.MultiIndex) and sym in raw.columns.get_level_values(0):
                        sub = raw[sym].dropna(how="all")
                        df = _normalize_yf(sub)
                except Exception:
                    df = None
            elif raw is not None and len(batch) == 1:
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
                except Exception as exc:  # noqa: BLE001
                    print(f"  {sym} fail: {exc}", flush=True)
                    continue
            if df is not None and len(df) >= MIN_BARS:
                df.to_csv(path)
            else:
                print(f"  {sym} skip bars={0 if df is None else len(df)}", flush=True)
        time.sleep(0.4)


def load_from_stress_cache(symbols: list[str]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols, 1):
        path = CACHE / f"{sym}.csv"
        if path.is_file():
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
        if i == 1 or i % 80 == 0 or i == len(symbols):
            print(f"load [{i}/{len(symbols)}] ok={len(frames)}", flush=True)
    return frames


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    want = sorted(
        {"SPY", "QQQ", "SMH"}
        | set(book_members("QQQ"))
        | set(book_members("SMH"))
        | set(book_members("SPY"))
    )
    bootstrap_cache(want)
    frames = load_from_stress_cache(want)
    for b in WEIGHTS:
        if b not in frames:
            raise SystemExit(f"missing bench {b} after bootstrap")
        print(
            f"bench {b}: {frames[b].index.min().date()}→{frames[b].index.max().date()} "
            f"n={len(frames[b])}",
            flush=True,
        )

    # Ensure enough pre-window history for 2020 start
    spy0 = frames["SPY"].index.min()
    if spy0 > pd.Timestamp("2019-06-01"):
        print(f"WARNING: SPY history starts {spy0.date()} — warm-up thin for 2020", flush=True)

    variants = {
        "v11": StructureGateConfig.v11(),
        "v13": StructureGateConfig.v13(),
    }
    reports: dict[str, list] = {k: [] for k in variants}
    compare = []

    for label, cfg in variants.items():
        for a, b in WINDOWS:
            print(f"\n=== {label} {a.date()}→{b.date()} ===", flush=True)
            rep = run_blend(frames, cfg, a, b, label=label)
            reports[label].append(rep)
            bl = rep["blend"]
            print(
                f"  ret={bl['total_return']*100:7.2f}% maxDD={bl['max_drawdown']*100:6.2f}% "
                f"sharpe={bl['sharpe']:.2f} vsSPY={bl['vs_spy_bh_pp']:+.1f}pp "
                f"vsStatic={bl['vs_static_etf_blend_pp']:+.1f}pp trades={bl['n_trades']}",
                flush=True,
            )

    for v11r, v13r in zip(reports["v11"], reports["v13"]):
        compare.append(
            {
                "start": v11r["start"],
                "end": v11r["end"],
                "v11_ret": v11r["blend"]["total_return"],
                "v13_ret": v13r["blend"]["total_return"],
                "delta_ret_pp": (v13r["blend"]["total_return"] - v11r["blend"]["total_return"]) * 100,
                "v11_maxdd": v11r["blend"]["max_drawdown"],
                "v13_maxdd": v13r["blend"]["max_drawdown"],
                "delta_maxdd_pp": (v13r["blend"]["max_drawdown"] - v11r["blend"]["max_drawdown"]) * 100,
                "v11_sharpe": v11r["blend"]["sharpe"],
                "v13_sharpe": v13r["blend"]["sharpe"],
                "v11_vs_spy_pp": v11r["blend"]["vs_spy_bh_pp"],
                "v13_vs_spy_pp": v13r["blend"]["vs_spy_bh_pp"],
                "v11_vs_static_pp": v11r["blend"]["vs_static_etf_blend_pp"],
                "v13_vs_static_pp": v13r["blend"]["vs_static_etf_blend_pp"],
                "v11_trades": v11r["blend"]["n_trades"],
                "v13_trades": v13r["blend"]["n_trades"],
                "v11_sleeves": v11r["sleeves"],
                "v13_sleeves": v13r["sleeves"],
                "spy_bh_ret": v11r["spy_bh"]["total_return"],
                "static_etf_ret": v11r["static_etf_403030"]["total_return"],
            }
        )

    summary = {
        "ok": True,
        "note": "OOS stress windows; Yahoo bootstrap 2019-01→2023-06; v13 knobs from prior tune",
        "data": {"cache": str(CACHE), "yf_start": YF_START, "yf_end": YF_END, "n_symbols": len(frames)},
        "v11": reports["v11"],
        "v13": reports["v13"],
        "compare": compare,
    }
    out_json = OUT / "stress_2020_2022_summary.json"
    out_json.write_text(json.dumps(summary, indent=2, default=float) + "\n")

    lines = [
        "=== Structure Gate v11 vs v13 — stress 2020 & 2022 ===",
        f"data: Yahoo {YF_START}→{YF_END}, symbols_ok={len(frames)}",
        "capital $50k | SPY40/QQQ30/SMH30 | Futu fees+3bps | next-open",
        "",
    ]
    for c in compare:
        lines.append(f"## {c['start']} → {c['end']}")
        lines.append(
            f"SPY B&H: {c['spy_bh_ret']*100:+.2f}% | static 40/30/30: {c['static_etf_ret']*100:+.2f}%"
        )
        lines.append(
            f"v11: ret={c['v11_ret']*100:+.2f}% maxDD={c['v11_maxdd']*100:.2f}% "
            f"sharpe={c['v11_sharpe']:.2f} vsSPY={c['v11_vs_spy_pp']:+.1f}pp "
            f"vsStatic={c['v11_vs_static_pp']:+.1f}pp trades={c['v11_trades']}"
        )
        lines.append(
            f"v13: ret={c['v13_ret']*100:+.2f}% maxDD={c['v13_maxdd']*100:.2f}% "
            f"sharpe={c['v13_sharpe']:.2f} vsSPY={c['v13_vs_spy_pp']:+.1f}pp "
            f"vsStatic={c['v13_vs_static_pp']:+.1f}pp trades={c['v13_trades']}"
        )
        lines.append(
            f"Δ(v13-v11): ret={c['delta_ret_pp']:+.2f}pp maxDD={c['delta_maxdd_pp']:+.2f}pp "
            f"trades={c['v13_trades']-c['v11_trades']:+d}"
        )
        for side, key in (("v11", "v11_sleeves"), ("v13", "v13_sleeves")):
            parts = [
                f"{s['book']} {s['total_return']*100:+.1f}%/DD{s['max_drawdown']*100:.1f}%/tr{s['n_trades']}"
                for s in c[key]
            ]
            lines.append(f"  {side} sleeves: " + " | ".join(parts))
        lines.append("")
    report = "\n".join(lines)
    (OUT / "stress_2020_2022_report.txt").write_text(report + "\n")
    print("\n" + report)
    print("wrote", out_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
