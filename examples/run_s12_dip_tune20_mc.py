#!/usr/bin/env python3
"""Monte Carlo: 20× S12+dip schemes, random QQQ/SOXX 30-name baskets, 1–12m."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.backtest.costs import CostModel
from qresearch.backtest.engine import BacktestEngine
from qresearch.data.loader import validate_ohlcv
from qresearch.regime.detector import VolatilityRegimeDetector
from qresearch.strategy.dip_probe import DipProbeEntryFilter
from qresearch.strategy.examples import RegimeAwareTrendStrategy
from qresearch.strategy.relative_strength import RelativeStrengthEntryFilter

OUT = ROOT / "examples" / "data" / "s12_dip_tune20"
WARMUP = 60
N_RUNS = 100
N_STOCKS = 30
SEED = 20260807
FEE_BPS, SLIP_BPS = 1.0, 3.0
HISTORY_START = "2023-01-01"
# Leave room for random 12m windows ending before this
HISTORY_END = "2026-08-01"


def fetch_ohlcv(ticker: str, start: str, end: str) -> pd.DataFrame:
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        raise ValueError(f"empty {ticker}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [str(c).lower() for c in raw.columns]
    df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def window_metrics(res, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> dict[str, float] | None:
    eq = res.equity.loc[start_ts:end_ts]
    if len(eq) < 2:
        return None
    r = eq.pct_change().fillna(0.0)
    dd = float((eq / eq.cummax() - 1.0).min())
    mu, sd = float(r.mean()), float(r.std(ddof=0))
    pos = res.positions.reindex(eq.index).fillna(0.0)
    n_tr = int((pos.diff().fillna(pos).abs() > 1e-12).sum())
    return {
        "total_return": float(eq.iloc[-1] / eq.iloc[0] - 1.0),
        "max_drawdown": dd,
        "sharpe": float((mu / sd) * np.sqrt(252)) if sd > 1e-12 else 0.0,
        "avg_exposure": float(pos.abs().mean()),
        "n_trades": float(n_tr),
    }


def build_strategy(row: pd.Series, bench_close: pd.Series) -> DipProbeEntryFilter:
    base = RegimeAwareTrendStrategy(
        fast=int(row.fast),
        slow=int(row.slow),
        high_vol_weight=0.0,
        detector=VolatilityRegimeDetector(
            lookback=int(row.vol_lb),
            high_vol_multiplier=float(row.vol_mult),
        ),
    )
    rs = RelativeStrengthEntryFilter(
        base=base,
        benchmark_close=bench_close,
        threshold=float(row.rs_thr),
        window=int(row.rs_win),
    )
    return DipProbeEntryFilter(
        base=rs,
        dip_threshold=float(row.dip_thr),
        dip_weight=float(row.dip_weight),
        drawdown_lookback=int(row.dd_lookback),
        dip_stop=float(row.dip_stop),
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    schemes = pd.read_csv(OUT / "schemes.csv")
    qqq_uni = pd.read_csv(ROOT / "examples" / "data" / "qqq100_6m" / "universe.csv")["symbol"].astype(str).tolist()
    sox_uni = pd.read_csv(ROOT / "examples" / "data" / "sox_universe.csv")["symbol"].astype(str).tolist()
    universes = {"QQQ": qqq_uni, "SOXX": sox_uni}

    print("Fetching benchmarks...")
    qqq = fetch_ohlcv("QQQ", HISTORY_START, HISTORY_END)
    soxx = fetch_ohlcv("SOXX", HISTORY_START, HISTORY_END)
    benches = {"QQQ": qqq["close"], "SOXX": soxx["close"]}
    cal = qqq.index.intersection(soxx.index).sort_values()

    all_tickers = sorted(set(qqq_uni) | set(sox_uni))
    print(f"Prefetching {len(all_tickers)} names {HISTORY_START}→{HISTORY_END}...")
    cache: dict[str, pd.DataFrame] = {}
    for i, t in enumerate(all_tickers):
        try:
            cache[t] = fetch_ohlcv(t, HISTORY_START, HISTORY_END)
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {t}: {exc}")
        if (i + 1) % 25 == 0:
            print(f"  cached {i + 1}/{len(all_tickers)} ok={len(cache)}")
    print(f"cache size={len(cache)}")

    engine = BacktestEngine(
        initial_capital=100_000.0,
        cost_model=CostModel(fee_bps=FEE_BPS, slippage_bps=SLIP_BPS),
        allow_short=False,
    )
    rng = np.random.default_rng(SEED)

    # Shared random schedule: same 100 (universe, months, window, picks) across schemes
    schedule = []
    for run in range(N_RUNS):
        uni_name = str(rng.choice(["QQQ", "SOXX"]))
        months = int(rng.integers(1, 13))
        eval_days = max(15, int(round(months * 21)))
        # need warmup + eval + buffer inside calendar
        max_start_i = len(cal) - eval_days - 1
        min_start_i = WARMUP + 90  # room for dd lookback
        if max_start_i <= min_start_i:
            raise RuntimeError("calendar too short")
        start_i = int(rng.integers(min_start_i, max_start_i + 1))
        end_i = start_i + eval_days - 1
        win_start = cal[start_i]
        win_end = cal[end_i]
        pool = [t for t in universes[uni_name] if t in cache and len(cache[t]) > WARMUP + eval_days]
        if len(pool) < N_STOCKS:
            raise RuntimeError(f"not enough names for {uni_name}: {len(pool)}")
        picks = rng.choice(pool, size=N_STOCKS, replace=False).tolist()
        schedule.append(
            {
                "run": run,
                "universe": uni_name,
                "months": months,
                "eval_days": eval_days,
                "win_start": win_start,
                "win_end": win_end,
                "picks": picks,
            }
        )

    run_rows: list[dict] = []
    for _, sch in schemes.iterrows():
        print(f"\n=== {sch.scheme} ({sch.note}) ===")
        for item in schedule:
            uni = item["universe"]
            bench = benches[uni]
            start_ts = pd.Timestamp(item["win_start"])
            end_ts = pd.Timestamp(item["win_end"])
            # bench return over eval window
            bseg = bench.loc[start_ts:end_ts].dropna()
            if len(bseg) < 2:
                continue
            bench_ret = float(bseg.iloc[-1] / bseg.iloc[0] - 1.0)

            rets, dds, shs, exps, trs = [], [], [], [], []
            ok = 0
            for t in item["picks"]:
                px = cache.get(t)
                if px is None:
                    continue
                try:
                    # history through end; need warmup before start
                    if len(px.loc[:start_ts]) < WARMUP:
                        continue
                    px_w = px.loc[:end_ts]
                    common = px_w.index.intersection(bench.index)
                    px_w = px_w.loc[common]
                    if len(px_w) < WARMUP + 2:
                        continue
                    strat = build_strategy(sch, bench)
                    m = window_metrics(engine.run(px_w, strat), start_ts, end_ts)
                    if m is None or np.isnan(m["total_return"]):
                        continue
                    rets.append(m["total_return"])
                    dds.append(m["max_drawdown"])
                    shs.append(m["sharpe"])
                    exps.append(m["avg_exposure"])
                    trs.append(m["n_trades"])
                    ok += 1
                except Exception:
                    continue
            if ok < 5:
                print(f"  run{item['run']} only {ok} ok — skip")
                continue
            mean_ret = float(np.mean(rets))
            run_rows.append(
                {
                    "scheme": sch.scheme,
                    "scheme_id": int(sch.scheme_id),
                    "note": sch.note,
                    "run": item["run"],
                    "universe": uni,
                    "months": item["months"],
                    "eval_days": item["eval_days"],
                    "win_start": start_ts.date().isoformat(),
                    "win_end": end_ts.date().isoformat(),
                    "n_names": ok,
                    "bench_ret": bench_ret,
                    "mean_ret": mean_ret,
                    "median_ret": float(np.median(rets)),
                    "mean_sharpe": float(np.mean(shs)),
                    "mean_mdd": float(np.mean(dds)),
                    "mean_vs_bench": mean_ret - bench_ret,
                    "pct_positive": float(np.mean([x > 0 for x in rets])),
                    "pct_beat_bench": float(np.mean([x > bench_ret for x in rets])),
                    "mean_trades": float(np.mean(trs)),
                    "mean_exposure": float(np.mean(exps)),
                }
            )
        done = sum(1 for r in run_rows if r["scheme"] == sch.scheme)
        if done:
            sub = [r for r in run_rows if r["scheme"] == sch.scheme]
            avg = float(np.mean([r["mean_ret"] for r in sub]))
            vs = float(np.mean([r["mean_vs_bench"] for r in sub]))
            print(f"  finished {done} runs | avg_ret={avg:+.2%} vs_bench={vs:+.2%}")

    rdf = pd.DataFrame(run_rows)
    rdf.to_csv(OUT / "mc_runs.csv", index=False)

    summary_rows = []
    for sid, g in rdf.groupby("scheme_id", sort=True):
        summary_rows.append(
            {
                "scheme_id": int(sid),
                "scheme": g["scheme"].iloc[0],
                "note": g["note"].iloc[0],
                "n_runs": len(g),
                "mean_ret": float(g["mean_ret"].mean()),
                "std_ret": float(g["mean_ret"].std(ddof=0)),
                "p10_ret": float(g["mean_ret"].quantile(0.10)),
                "p50_ret": float(g["mean_ret"].median()),
                "p90_ret": float(g["mean_ret"].quantile(0.90)),
                "mean_sharpe": float(g["mean_sharpe"].mean()),
                "mean_mdd": float(g["mean_mdd"].mean()),
                "mean_vs_bench": float(g["mean_vs_bench"].mean()),
                "pct_beat_bench": float(g["pct_beat_bench"].mean()),
                "pct_positive": float(g["pct_positive"].mean()),
                "pct_runs_pos": float((g["mean_ret"] > 0).mean()),
                "mean_months": float(g["months"].mean()),
                "pct_universe_qqq": float((g["universe"] == "QQQ").mean()),
                "mean_exposure": float(g["mean_exposure"].mean()),
                "mean_trades": float(g["mean_trades"].mean()),
            }
        )
    sdf = pd.DataFrame(summary_rows).sort_values("mean_vs_bench", ascending=False)
    sdf.to_csv(OUT / "scheme_summary.csv", index=False)

    cfg = {
        "n_schemes": len(schemes),
        "n_runs": N_RUNS,
        "n_stocks": N_STOCKS,
        "months_range": [1, 12],
        "warmup_bars": WARMUP,
        "seed": SEED,
        "fee_bps": FEE_BPS,
        "slippage_bps": SLIP_BPS,
        "history": [HISTORY_START, HISTORY_END],
        "base": "S12 + RS entry + dip probe",
    }
    (OUT / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    print("\n===== TOP by mean_vs_bench =====")
    cols = [
        "scheme",
        "mean_ret",
        "mean_vs_bench",
        "mean_mdd",
        "pct_beat_bench",
        "pct_runs_pos",
        "mean_exposure",
    ]
    show = sdf[cols].copy()
    for c in cols[1:]:
        show[c] = show[c].map(lambda v: f"{v:.2%}")
    print(show.to_string(index=False))
    print(f"\nsaved → {OUT}")


if __name__ == "__main__":
    main()
