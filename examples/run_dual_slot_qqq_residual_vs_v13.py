#!/usr/bin/env python3
"""Research run: V13 sleeves, but each sleeve may hold two stocks.

Not a new strategy version. Same StructureGateConfig.v13() modes, same G1
Emerging-RS entry/exit rules. Only the book sizing changes:

- SPY sleeve and QQQ sleeve each keep a 50% capital budget.
- In ers mode a sleeve may hold up to 2 names. Each full slot is 25% of
  *total* capital (50% of that sleeve). An unfilled slot stays in QQQ.
- A half-exit (weaken) cuts that name to 12.5% of total; the freed piece
  goes to QQQ.
- In strong mode the single leader is also 25% of total, and the other
  25% of that sleeve stays in QQQ.
- Bench mode still holds that sleeve's own ETF (SPY sleeve → SPY).
- Cash mode is still cash. A 1-day stock drop of 8% or more still flattens
  the whole sleeve to cash, same as V13.

Window: continuous book from 2019-01-01 through the latest cached bar
(about seven full calendar years plus 2026 YTD). Yearly returns are
calendar slices of that one path, not independent yearly restarts.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.backtest.futu_costs import FutuUsEquityFees  # noqa: E402
from qresearch.data.loader import validate_ohlcv  # noqa: E402
from qresearch.strategy.emerging_rs_wave import (  # noqa: E402
    EmergingRSWaveConfig,
    market_gate,
)
from qresearch.strategy.structure_gate import (  # noqa: E402
    V13_BOOK_WEIGHTS,
    StructureGateConfig,
    blend_structure_gate_books,
    label_structure_modes,
    simulate_structure_gate,
    strong_leader_weights,
)
from run_emerging_rs_wave_gates import metrics  # type: ignore  # noqa: E402
from run_structure_gate_v13_blend import (  # type: ignore  # noqa: E402
    align_panel,
    book_members,
)

OUT = ROOT / "examples" / "data" / "dual_slot_qqq_residual"
CACHE = OUT / "cache_ohlcv"
CAPITAL = 50_000.0
WEIGHTS = dict(V13_BOOK_WEIGHTS)
MIN_BARS = 220
FETCH_START = "2017-01-01"
TRADE_START = pd.Timestamp("2019-01-01")
FETCH_END = "2026-10-07"


def _normalize_yf(raw: pd.DataFrame) -> pd.DataFrame | None:
    if raw is None or len(raw) < 30:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.copy()
        raw.columns = [str(c[0]).lower() for c in raw.columns]
    else:
        raw = raw.copy()
        raw.columns = [str(c).lower() for c in raw.columns]
    need = ["open", "high", "low", "close", "volume"]
    if any(c not in raw.columns for c in need):
        return None
    cleaned = raw[need].dropna()
    if cleaned.empty:
        return None
    ok = (cleaned["high"] >= cleaned[["open", "close"]].max(axis=1)) & (
        cleaned["low"] <= cleaned[["open", "close"]].min(axis=1)
    )
    cleaned = cleaned.loc[ok]
    if len(cleaned) < 30:
        return None
    try:
        df = validate_ohlcv(cleaned)
    except Exception:
        return None
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[~df.index.duplicated(keep="last")].sort_index()


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    try:
        raw = pd.read_csv(path, index_col=0, parse_dates=True)
        raw.columns = [str(c).lower() for c in raw.columns]
        df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
    except Exception:
        return None
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[~df.index.duplicated(keep="last")].sort_index()


def _slice_batch(raw: pd.DataFrame, sym: str, batch_n: int) -> pd.DataFrame | None:
    if raw is None or len(raw) == 0:
        return None
    if not isinstance(raw.columns, pd.MultiIndex):
        return _normalize_yf(raw) if batch_n == 1 else None
    levels = [raw.columns.get_level_values(i) for i in range(raw.columns.nlevels)]
    if sym in levels[0]:
        return _normalize_yf(raw[sym].dropna(how="all"))
    if sym in levels[-1]:
        return _normalize_yf(raw.xs(sym, axis=1, level=-1).dropna(how="all"))
    return None


def download_cache(symbols: list[str]) -> None:
    import yfinance as yf

    CACHE.mkdir(parents=True, exist_ok=True)
    need = []
    fresh_cutoff = pd.Timestamp("2026-09-30")
    for sym in symbols:
        df = _read_csv(CACHE / f"{sym}.csv")
        if df is None or len(df) < MIN_BARS or df.index.max() < fresh_cutoff:
            need.append(sym)
    print(f"cache {CACHE} missing_or_stale={len(need)} / {len(symbols)}", flush=True)
    if not need:
        return
    for i in range(0, len(need), 40):
        batch = need[i : i + 40]
        print(f"yf {i + 1}-{i + len(batch)} / {len(need)} {batch[:4]}…", flush=True)
        raw = None
        try:
            raw = yf.download(
                batch,
                start=FETCH_START,
                end=FETCH_END,
                auto_adjust=True,
                progress=False,
                threads=True,
                group_by="ticker",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  batch failed: {exc}", flush=True)
        for sym in batch:
            fresh = _slice_batch(raw, sym, len(batch)) if raw is not None else None
            if fresh is None:
                try:
                    one = yf.download(
                        sym,
                        start=FETCH_START,
                        end=FETCH_END,
                        auto_adjust=True,
                        progress=False,
                        threads=False,
                    )
                    fresh = _normalize_yf(one)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {sym} fail: {exc}", flush=True)
                    continue
            if fresh is not None and len(fresh) >= MIN_BARS:
                fresh.to_csv(CACHE / f"{sym}.csv")
            else:
                print(f"  {sym} skip bars={0 if fresh is None else len(fresh)}", flush=True)
        time.sleep(0.2)


def load_frames(symbols: list[str]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols, 1):
        df = _read_csv(CACHE / f"{sym}.csv")
        if df is not None and len(df) >= MIN_BARS:
            frames[sym] = df
        if i == 1 or i % 100 == 0 or i == len(symbols):
            print(f"load [{i}/{len(symbols)}] ok={len(frames)}", flush=True)
    return frames


def ers_two_slot_weights(
    closes: pd.DataFrame,
    bench_close: pd.Series,
    cfg: EmergingRSWaveConfig,
) -> pd.DataFrame:
    """Up to two G1 names. Full slot = 0.5 of the sleeve, half slot = 0.25."""
    px = closes.astype(float).sort_index()
    bench = bench_close.astype(float).reindex(px.index).ffill()
    gate_on = market_gate(bench, "G1").reindex(px.index).fillna(False)

    stock_ret_s = px / px.shift(cfg.short_window) - 1.0
    stock_ret_m = px / px.shift(cfg.mid_window) - 1.0
    stock_ret_l = px / px.shift(cfg.long_window) - 1.0
    bench_s = bench / bench.shift(cfg.short_window) - 1.0
    bench_m = bench / bench.shift(cfg.mid_window) - 1.0
    bench_l = bench / bench.shift(cfg.long_window) - 1.0
    excess_s = stock_ret_s.sub(bench_s, axis=0)
    excess_m = stock_ret_m.sub(bench_m, axis=0)
    excess_l = stock_ret_l.sub(bench_l, axis=0)
    sma = px.rolling(cfg.exit_ma, min_periods=cfg.exit_ma).mean()

    pos_s = excess_s > 0.0
    persist = pos_s.copy()
    for k in range(1, cfg.persist_days):
        persist = persist & pos_s.shift(k).fillna(False)
    just_turned = persist & pos_s.shift(cfg.persist_days).eq(False)
    entry_ok = just_turned & (excess_m > 0.0) & (excess_l <= cfg.already_strong_cap) & persist

    symbols = list(px.columns)
    entry = entry_ok.to_numpy(dtype=bool)
    ex = excess_s.to_numpy(dtype=float)
    sma_a = sma.to_numpy(dtype=float)
    px_a = px.to_numpy(dtype=float)
    gate = gate_on.to_numpy(dtype=bool)
    weights = np.zeros(px_a.shape, dtype=float)
    full_w = 0.5
    half_w = 0.25
    dd_stop = abs(float(cfg.peak_dd_stop))
    # slot: [col, weight, peak]
    slots: list[list] = []

    for i in range(px_a.shape[0]):
        kept: list[list] = []
        for col, w, peak in slots:
            price = float(px_a[i, col])
            if np.isfinite(price) and (not np.isfinite(peak) or price > peak):
                peak = price
            ex_s = float(ex[i, col])
            ma = float(sma_a[i, col])
            weak = (np.isfinite(ex_s) and ex_s < 0.0) or (
                np.isfinite(ma) and np.isfinite(price) and price < ma
            )
            dd = (
                price / peak - 1.0
                if np.isfinite(peak) and peak > 0 and np.isfinite(price)
                else 0.0
            )
            if dd <= -dd_stop or not bool(gate[i]):
                continue
            if weak:
                if cfg.weaken_goes_flat or w <= half_w + 1e-12:
                    continue
                w = half_w
            kept.append([col, w, peak])
        slots = kept
        held = {int(s[0]) for s in slots}
        if len(slots) < 2 and bool(gate[i]):
            scored: list[tuple[float, int]] = []
            for c in np.flatnonzero(entry[i]):
                c = int(c)
                if c in held:
                    continue
                v = float(ex[i, c])
                if np.isfinite(v):
                    scored.append((v, c))
            scored.sort(key=lambda x: (-x[0], symbols[x[1]]))
            for _v, c in scored:
                if len(slots) >= 2:
                    break
                price = float(px_a[i, c])
                slots.append([c, full_w, price if np.isfinite(price) else np.nan])
                held.add(c)
        for col, w, _peak in slots:
            weights[i, int(col)] = w
    return pd.DataFrame(weights, index=px.index, columns=symbols)


def _sig(targets: dict[tuple[str, str], float]) -> tuple:
    return tuple(
        sorted((kind, sym, round(float(w), 6)) for (kind, sym), w in targets.items() if w > 1e-8)
    )


def simulate_dual_slot_sleeve(
    book: str,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    bench_open: pd.Series,
    bench_close: pd.Series,
    qqq_open: pd.Series,
    qqq_close: pd.Series,
    *,
    capital: float,
    start: pd.Timestamp,
    config: StructureGateConfig,
) -> tuple[pd.Series, pd.Series, int]:
    """Next-open sleeve. Returns (equity, n_stock_names, n_trades)."""
    cfg = config
    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    bench_fees = fees.with_slippage(cfg.bench_slippage_bps)
    stock_fees = fees.with_slippage(cfg.stock_slippage_bps)
    ers_cfg = cfg.ers_config or EmergingRSWaveConfig()

    mode, _meta = label_structure_modes(
        bench_close,
        closes,
        config=cfg,
        bench_volume=None,
    )
    ers_w = ers_two_slot_weights(closes, bench_close, ers_cfg)
    strong_w = strong_leader_weights(closes, bench_close, config=cfg)

    px = closes.astype(float).sort_index()
    op = opens.astype(float).reindex(px.index)
    qo = qqq_open.astype(float).reindex(px.index).ffill()
    qc = qqq_close.astype(float).reindex(px.index).ffill()
    bo = bench_open.astype(float).reindex(px.index)
    bc = bench_close.astype(float).reindex(px.index)
    mode = mode.reindex(px.index).fillna("cash")
    ers_w = ers_w.reindex(px.index).fillna(0.0)
    strong_w = strong_w.reindex(index=px.index, columns=px.columns).fillna(0.0)

    dates = list(px.index)
    cash = float(capital)
    # key (kind, sym) -> shares. kind is "stock" or "etf".
    positions: dict[tuple[str, str], float] = {}
    pending: dict[tuple[str, str], float] = {}
    committed: tuple | None = None
    n_trades = 0
    equity_rows: list[float] = []
    hold_rows: list[float] = []
    eq_index: list[pd.Timestamp] = []

    def price(key: tuple[str, str], dt: pd.Timestamp, field: str) -> float:
        kind, sym = key
        if kind == "etf" and sym == "QQQ":
            series = qo if field == "open" else qc
            return float(series.at[dt])
        if kind == "etf":
            series = bo if field == "open" else bc
            return float(series.at[dt])
        frame = op if field == "open" else px
        if sym not in frame.columns:
            return float("nan")
        return float(frame.at[dt, sym])

    def mark(dt: pd.Timestamp, field: str) -> float:
        total = cash
        for key, sh in positions.items():
            p = price(key, dt, field)
            if np.isfinite(p) and sh > 0:
                total += sh * p
        return total

    def fee_for(key: tuple[str, str]) -> FutuUsEquityFees:
        return stock_fees if key[0] == "stock" else bench_fees

    def sell(key: tuple[str, str], shares: float, dt: pd.Timestamp) -> None:
        nonlocal cash, n_trades
        have = positions.get(key, 0.0)
        shares = min(float(shares), have)
        if shares <= 1e-9:
            return
        p = price(key, dt, "open")
        if not np.isfinite(p) or p <= 0:
            return
        notional = shares * p
        cost = float(fee_for(key).total_cost_usd(notional, p))
        cash += notional - cost
        left = have - shares
        if left <= 1e-9:
            positions.pop(key, None)
        else:
            positions[key] = left
        n_trades += 1

    def buy(key: tuple[str, str], shares: float, dt: pd.Timestamp) -> None:
        nonlocal cash, n_trades
        shares = float(np.floor(shares))
        if shares < 1:
            return
        p = price(key, dt, "open")
        if not np.isfinite(p) or p <= 0:
            return
        notional = shares * p
        cost = float(fee_for(key).total_cost_usd(notional, p))
        if notional + cost > cash + 1e-6:
            shares = float(np.floor((cash * 0.999) / p))
            if shares < 1:
                return
            notional = shares * p
            cost = float(fee_for(key).total_cost_usd(notional, p))
            if notional + cost > cash + 1e-6:
                return
        cash -= notional + cost
        positions[key] = positions.get(key, 0.0) + shares
        n_trades += 1

    def targets_for(dt: pd.Timestamp) -> dict[tuple[str, str], float]:
        m = str(mode.at[dt])
        if m == "cash":
            return {}
        if m == "bench":
            return {("etf", book): 1.0}
        if m == "strong":
            row = strong_w.loc[dt]
            active = row[row.abs() > 1e-12]
            if len(active) == 0:
                return {}
            return {("stock", str(active.index[0])): 0.5, ("etf", "QQQ"): 0.5}
        row = ers_w.loc[dt]
        active = row[row.abs() > 1e-12]
        out: dict[tuple[str, str], float] = {}
        for sym, w in active.items():
            out[("stock", str(sym))] = float(w)
        used = float(sum(out.values()))
        resid = 1.0 - used
        if resid > 1e-8:
            out[("etf", "QQQ")] = resid
        return out

    def rebalance(dt: pd.Timestamp, targets: dict[tuple[str, str], float]) -> None:
        eq = mark(dt, "open")
        desired: dict[tuple[str, str], float] = {}
        for key, w in targets.items():
            if w <= 1e-8:
                continue
            p = price(key, dt, "open")
            if not np.isfinite(p) or p <= 0:
                if key in positions:
                    desired[key] = positions[key]
                continue
            shares = float(np.floor(eq * float(w) / p))
            if shares >= 1:
                desired[key] = shares
            elif key in positions:
                desired[key] = 0.0
        for key in list(positions.keys()):
            want = desired.get(key, 0.0)
            have = positions.get(key, 0.0)
            if have > want + 1e-9:
                sell(key, have - want, dt)
        for key, want in desired.items():
            have = positions.get(key, 0.0)
            if want > have + 1e-9:
                buy(key, want - have, dt)

    for dt in dates:
        if dt >= start:
            sig = _sig(pending)
            if sig != committed:
                rebalance(dt, pending)
                committed = sig
            eq_index.append(dt)
            equity_rows.append(mark(dt, "close"))
            hold_rows.append(float(sum(1 for kind, _sym in positions if kind == "stock")))

        pending = targets_for(dt)
        if (
            cfg.risk_override_enabled
            and dt >= start
            and any(kind == "stock" for kind, _sym in positions)
        ):
            loc = px.index.get_loc(dt)
            if isinstance(loc, int) and loc > 0:
                prev_dt = px.index[loc - 1]
                crashed = False
                for key in list(positions):
                    if key[0] != "stock":
                        continue
                    prev = price(key, prev_dt, "close")
                    now = price(key, dt, "close")
                    if np.isfinite(prev) and prev > 0 and np.isfinite(now):
                        if now / prev - 1.0 <= -abs(float(cfg.risk_override_stock_1d)):
                            crashed = True
                            break
                if crashed:
                    pending = {}

        if dt < start:
            cash = float(capital)
            positions.clear()
            committed = None

    equity = pd.Series(equity_rows, index=pd.DatetimeIndex(eq_index), name="equity")
    holds = pd.Series(hold_rows, index=equity.index, name="n_stocks")
    return equity, holds, n_trades


def yearly_table(equity: pd.Series, capital: float) -> list[dict]:
    eq = equity.dropna()
    rows = []
    prev = float(capital)
    for year, sub in eq.groupby(eq.index.year):
        end = float(sub.iloc[-1])
        rows.append(
            {
                "year": int(year),
                "return": end / prev - 1.0,
                "end_equity": end,
                "partial": bool(sub.index.max() < pd.Timestamp(f"{int(year)}-12-15")),
            }
        )
        prev = end
    return rows


def _pct(x: float) -> str:
    return f"{100.0 * x:+.2f}%"


def _pp(x: float) -> str:
    return f"{x:+.2f}pp"


def main() -> int:
    t0 = time.time()
    symbols = sorted(set(book_members("SPY")) | set(book_members("QQQ")) | {"SPY", "QQQ"})
    download_cache(symbols)
    frames = load_frames(symbols)
    for b in ("SPY", "QQQ"):
        if b not in frames:
            print(f"missing {b}", file=sys.stderr)
            return 1
    end = min(frames["SPY"].index.max(), frames["QQQ"].index.max())
    start = TRADE_START
    cfg = StructureGateConfig.v13()
    print(
        f"window {start.date()} → {end.date()} symbols={len(frames)} capital={CAPITAL:,.0f}",
        flush=True,
    )

    v13_books = {}
    dual_books = {}
    dual_holds = {}
    sleeve_notes = []
    qqq = frames["QQQ"]
    for book, w in WEIGHTS.items():
        sleeve_cap = CAPITAL * w
        bdf = frames[book].loc[:end]
        opens, closes = align_panel(frames, book_members(book), bdf.index)
        print(f"\n=== {book} members={len(closes.columns)} sleeve={sleeve_cap:,.0f} ===", flush=True)
        fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
        print("  v13…", flush=True)
        sim = simulate_structure_gate(
            opens,
            closes,
            bdf["open"],
            bdf["close"],
            capital=sleeve_cap,
            start=start,
            fees=fees,
            config=cfg,
            bench_volume=bdf["volume"] if "volume" in bdf.columns else None,
        )
        v13_books[book] = sim
        mv = metrics(sim.equity, sleeve_cap)
        print(
            f"  v13 ret={mv['total_return']*100:.2f}% maxDD={mv['max_drawdown']*100:.2f}% "
            f"trades={len(sim.trades)}",
            flush=True,
        )
        print("  dual-slot…", flush=True)
        eq, holds, n_tr = simulate_dual_slot_sleeve(
            book,
            opens,
            closes,
            bdf["open"],
            bdf["close"],
            qqq["open"],
            qqq["close"],
            capital=sleeve_cap,
            start=start,
            config=cfg,
        )
        dual_books[book] = type("R", (), {"equity": eq})()
        dual_holds[book] = holds
        md = metrics(eq, sleeve_cap)
        print(
            f"  dual ret={md['total_return']*100:.2f}% maxDD={md['max_drawdown']*100:.2f}% "
            f"trades={n_tr} avg_names={float(holds.mean()):.2f}",
            flush=True,
        )
        sleeve_notes.append(
            {
                "book": book,
                "n_members": int(len(closes.columns)),
                "v13_total_return": mv["total_return"],
                "v13_max_drawdown": mv["max_drawdown"],
                "v13_trades": int(len(sim.trades)),
                "dual_total_return": md["total_return"],
                "dual_max_drawdown": md["max_drawdown"],
                "dual_trades": int(n_tr),
                "dual_avg_stock_names": float(holds.mean()),
            }
        )

    v13_eq, _panel = blend_structure_gate_books(v13_books, WEIGHTS, capital=CAPITAL)
    dual_eq, _panel2 = blend_structure_gate_books(dual_books, WEIGHTS, capital=CAPITAL)
    v13_eq = v13_eq.loc[start:end].dropna()
    dual_eq = dual_eq.loc[start:end].dropna()
    common = v13_eq.index.intersection(dual_eq.index)
    v13_eq = v13_eq.reindex(common).ffill()
    dual_eq = dual_eq.reindex(common).ffill()

    y_v = {r["year"]: r for r in yearly_table(v13_eq, CAPITAL)}
    y_d = {r["year"]: r for r in yearly_table(dual_eq, CAPITAL)}
    years = sorted(set(y_v) | set(y_d))
    rows = []
    print("\n年份 | 雙槽+QQQ | V13 | 相對V13")
    for y in years:
        dv = y_d[y]["return"]
        vv = y_v[y]["return"]
        label = f"{y} YTD" if y_d[y]["partial"] else str(y)
        gap = (dv - vv) * 100.0
        rows.append(
            {
                "year": label,
                "dual_slot": dv,
                "v13": vv,
                "vs_v13_pp": gap,
            }
        )
        print(f"{label:8} | {_pct(dv):>10} | {_pct(vv):>10} | {_pp(gap):>10}")

    m_d = metrics(dual_eq, CAPITAL)
    m_v = metrics(v13_eq, CAPITAL)
    # Seven complete calendar years 2019-2025, if present.
    full_years = [y for y in years if y <= 2025]
    def _span(eq: pd.Series, year_rows: dict, ys: list[int]) -> float:
        if not ys:
            return float("nan")
        end_eq = year_rows[ys[-1]]["end_equity"]
        return end_eq / CAPITAL - 1.0

    span_d = _span(dual_eq, y_d, full_years)
    span_v = _span(v13_eq, y_v, full_years)
    print(
        f"\n全樣本 {v13_eq.index.min().date()}→{v13_eq.index.max().date()} "
        f"雙槽 {_pct(m_d['total_return'])} V13 {_pct(m_v['total_return'])} "
        f"差 {_pp((m_d['total_return'] - m_v['total_return']) * 100)}"
    )
    print(
        f"最大回撤 雙槽 {_pct(m_d['max_drawdown'])} V13 {_pct(m_v['max_drawdown'])}"
    )
    print(
        f"2019-2025 累計 雙槽 {_pct(span_d)} V13 {_pct(span_v)} "
        f"差 {_pp((span_d - span_v) * 100)}"
    )
    hold_panel = pd.DataFrame(dual_holds).reindex(common).fillna(0.0)
    avg_names = float(hold_panel.sum(axis=1).mean())
    print(f"雙槽平均同時持股數（兩袖口合計）={avg_names:.2f}")
    print(f"elapsed {time.time() - t0:.1f}s", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "note": (
            "Not a new version. V13 modes and G1 entry/exit. "
            "Each sleeve up to 2 ERS names at 25% of total capital; "
            "unfilled sleeve weight and the strong-mode residual stay in QQQ."
        ),
        "start": str(v13_eq.index.min().date()),
        "end": str(v13_eq.index.max().date()),
        "capital": CAPITAL,
        "weights": WEIGHTS,
        "yearly": rows,
        "full": {
            "dual_total_return": m_d["total_return"],
            "v13_total_return": m_v["total_return"],
            "vs_v13_pp": (m_d["total_return"] - m_v["total_return"]) * 100,
            "dual_max_drawdown": m_d["max_drawdown"],
            "v13_max_drawdown": m_v["max_drawdown"],
            "dual_sharpe": m_d["sharpe"],
            "v13_sharpe": m_v["sharpe"],
            "dual_end_equity": m_d["end_equity"],
            "v13_end_equity": m_v["end_equity"],
            "span_2019_2025_dual": span_d,
            "span_2019_2025_v13": span_v,
            "avg_stock_names": avg_names,
        },
        "sleeves": sleeve_notes,
        "rules": {
            "ers_slots_per_sleeve": 2,
            "full_slot_of_total": 0.25,
            "residual": "QQQ",
            "strong_leader_of_total": 0.25,
            "strong_residual": "QQQ",
            "bench": "sleeve ETF",
            "risk_override_stock_1d": cfg.risk_override_stock_1d,
        },
    }
    (OUT / "yearly_vs_v13.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    dual_eq.to_csv(OUT / "equity_dual.csv", header=["equity"])
    v13_eq.to_csv(OUT / "equity_v13.csv", header=["equity"])
    print(f"wrote {OUT / 'yearly_vs_v13.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
