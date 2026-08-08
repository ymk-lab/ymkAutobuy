#!/usr/bin/env python3
"""Structure Gate v8 daily job: Longbridge market data + paper trade only.

Modes (argv[1] or QRESEARCH_SG_PAPER_MODE):
  signal   — compute latest mode / target, no orders
  once     — signal + optional paper submit
  backtest — simulate_structure_gate on Longbridge panel (no orders)

Safety:
  - Default dry-run; venue submit only when QRESEARCH_SG_PAPER_SUBMIT=1
  - Paper-only: refuse submit unless QRESEARCH_SG_PAPER_ONLY is truthy (default)
  - Does not use QRESEARCH_LB_SUBMIT (G1 flag) to avoid accidental live coupling

Typical cron (America/New_York):
  35 16 * * 1-5  python examples/run_structure_gate_v8_paper_daily.py once
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.brokers.longbridge import LongbridgeBrokerAdapter, has_longbridge_credentials
from qresearch.brokers.longbridge.config import load_dotenv_if_present, load_longbridge_config
from qresearch.brokers.longbridge.history import candlesticks_to_ohlcv
from qresearch.brokers.longbridge.symbols import normalize_symbol
from qresearch.data.loader import validate_ohlcv
from qresearch.execution.targets import TargetWeightExecutor
from qresearch.strategy.emerging_rs_wave import EmergingRSWaveBook, EmergingRSWaveConfig
from qresearch.strategy.structure_gate import (
    StructureGateConfig,
    label_structure_modes,
    simulate_structure_gate,
    strong_leader_weights,
)

from run_emerging_rs_wave_gates import (  # type: ignore
    UNIVERSE as QQQ_UNIVERSE,
    simulate_book,
)
from run_emerging_rs_wave_soxx import UNIVERSE as SEMI_UNIVERSE  # type: ignore
from run_structure_gate_bakeoff import soft_pass  # type: ignore
from qresearch.strategy.regime_playbook import simulate_bench_bh, simulate_cash

MIN_BARS = 220
WARM_START = date(2023, 1, 1)
DEFAULT_OUT = ROOT / "examples" / "data" / "structure_gate_v8_paper"
DEFAULT_BOOK = "QQQ"
CAPITAL = 50_000.0

US_BOOKS: dict[str, dict] = {
    "QQQ": {"bench": "QQQ", "universe": list(QQQ_UNIVERSE)},
    "SMH": {"bench": "SMH", "universe": list(SEMI_UNIVERSE)},
    "SOXX": {"bench": "SOXX", "universe": list(SEMI_UNIVERSE)},
    "SPY": {
        "bench": "SPY",
        "universe_file": ROOT / "examples" / "data" / "emerging_rs_wave_spy" / "universe.txt",
    },
    "DIA": {
        "bench": "DIA",
        "universe_file": ROOT / "examples" / "data" / "emerging_rs_wave_dia" / "universe.txt",
    },
    "IWM": {
        "bench": "IWM",
        "universe_file": ROOT / "examples" / "data" / "emerging_rs_wave_iwm" / "universe.txt",
    },
    "XLF": {
        "bench": "XLF",
        "universe_file": ROOT / "examples" / "data" / "emerging_rs_wave_xlf" / "universe.txt",
    },
    "XLK": {
        "bench": "XLK",
        "universe_file": ROOT / "examples" / "data" / "emerging_rs_wave_xlk" / "universe.txt",
    },
    "XBI": {
        "bench": "XBI",
        "universe_file": ROOT / "examples" / "data" / "emerging_rs_wave_xbi" / "universe.txt",
    },
    "XLE": {
        "bench": "XLE",
        "universe_file": ROOT / "examples" / "data" / "emerging_rs_wave_xle" / "universe.txt",
    },
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float | None = None) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def out_dir() -> Path:
    path = Path(os.getenv("QRESEARCH_SG_PAPER_OUT", str(DEFAULT_OUT)))
    path.mkdir(parents=True, exist_ok=True)
    (path / "cache_ohlcv").mkdir(parents=True, exist_ok=True)
    (path / "logs").mkdir(parents=True, exist_ok=True)
    (path / "backtest").mkdir(parents=True, exist_ok=True)
    return path


def book_name() -> str:
    return os.getenv("QRESEARCH_SG_BOOK", DEFAULT_BOOK).strip().upper()


def resolve_universe(book: str) -> tuple[str, list[str]]:
    if book not in US_BOOKS:
        raise SystemExit(f"unsupported book={book}; choose from {sorted(US_BOOKS)}")
    spec = US_BOOKS[book]
    bench = str(spec["bench"])
    if spec.get("universe"):
        members = [str(s) for s in spec["universe"] if str(s) != bench]
        return bench, members
    uf = Path(spec["universe_file"])
    if not uf.is_file():
        raise SystemExit(f"{book}: missing universe file {uf}")
    members = [
        line.strip().upper()
        for line in uf.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#") and line.strip().upper() != bench
    ]
    return bench, members


def load_cache(cache: Path, symbol: str) -> pd.DataFrame | None:
    path = cache / f"{symbol}.csv"
    if not path.is_file() or path.stat().st_size < 64:
        return None
    try:
        raw = pd.read_csv(path, index_col=0, parse_dates=True)
        raw.columns = [str(c).lower() for c in raw.columns]
        need = ["open", "high", "low", "close", "volume"]
        if any(c not in raw.columns for c in need):
            return None
        df = validate_ohlcv(raw[need].dropna())
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        if len(df) < MIN_BARS:
            return None
        return df[~df.index.duplicated(keep="last")].sort_index()
    except Exception:
        return None


def save_cache(cache: Path, symbol: str, df: pd.DataFrame) -> None:
    out = df.copy()
    out.index.name = "datetime"
    out.to_csv(cache / f"{symbol}.csv")


def fetch_symbol(quote_ctx, symbol: str, end: date) -> pd.DataFrame | None:
    from longbridge.openapi import AdjustType, Period

    lb = f"{symbol}.US"
    for attempt in range(1, 4):
        try:
            candles = list(
                quote_ctx.history_candlesticks_by_date(
                    lb,
                    Period.Day,
                    AdjustType.ForwardAdjust,
                    WARM_START,
                    end,
                )
            )
            if not candles:
                return None
            df = candlesticks_to_ohlcv(candles)
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            return df
        except Exception as exc:  # noqa: BLE001
            if attempt == 3:
                print(f"fetch fail {symbol}: {exc}")
            time.sleep(0.35 * attempt)
    return None


def load_panel(symbols: list[str], cache: Path) -> dict[str, pd.DataFrame]:
    from longbridge.openapi import QuoteContext

    end = date.today() + timedelta(days=1)
    quote_ctx = QuoteContext(load_longbridge_config())
    frames: dict[str, pd.DataFrame] = {}
    refresh = _env_bool("QRESEARCH_REFRESH_CACHE", True)
    for i, sym in enumerate(symbols, 1):
        cached = None if refresh else load_cache(cache, sym)
        if cached is not None and cached.index.max().date() >= date.today() - timedelta(days=3):
            frames[sym] = cached
            continue
        df = fetch_symbol(quote_ctx, sym, end)
        if df is None:
            cached = load_cache(cache, sym)
            if cached is not None:
                frames[sym] = cached
                print(f"[{i}/{len(symbols)}] stale-cache {sym}")
            else:
                print(f"[{i}/{len(symbols)}] skip {sym}")
            continue
        save_cache(cache, sym, df)
        frames[sym] = df
        if i == 1 or i % 20 == 0 or i == len(symbols):
            print(f"[{i}/{len(symbols)}] ok {sym} bars={len(df)}")
        time.sleep(0.05)
    return frames


def build_closes(
    frames: dict[str, pd.DataFrame], bench: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.Series | None]:
    """Return opens, closes, bench_open, bench_close, bench_volume."""
    if bench not in frames:
        raise SystemExit(f"bench {bench} history failed")
    bdf = frames[bench]
    idx = bdf.index
    stock = {s: df for s, df in frames.items() if s != bench}
    opens = pd.DataFrame({s: stock[s]["open"].reindex(idx) for s in stock})
    closes = pd.DataFrame({s: stock[s]["close"].reindex(idx) for s in stock})
    keep = [c for c in closes.columns if closes[c].notna().sum() >= MIN_BARS]
    opens = opens[keep]
    closes = closes[keep]
    vol = bdf["volume"] if "volume" in bdf.columns else None
    return opens, closes, bdf["open"], bdf["close"], vol


def latest_target(
    closes: pd.DataFrame,
    bench_close: pd.Series,
    bench_sym: str,
    *,
    bench_volume: pd.Series | None = None,
    cfg: StructureGateConfig | None = None,
) -> tuple[dict[str, float], dict]:
    cfg = cfg or StructureGateConfig.v8()
    mode, meta_df = label_structure_modes(
        bench_close, closes, config=cfg, bench_volume=bench_volume
    )
    last = closes.index.max()
    m = str(mode.loc[last])
    target_raw: dict[str, float] = {}
    if m == "bench":
        target_raw = {bench_sym: 1.0}
    elif m == "ers":
        book = EmergingRSWaveBook(gate="G1", config=cfg.ers_config or EmergingRSWaveConfig())
        weights, log = book.generate_weights(closes, bench_close)
        row = weights.loc[last]
        active = row[row.abs() > 1e-12]
        if len(active):
            target_raw = {str(active.index[0]): float(active.iloc[0])}
        events = []
        if len(log):
            recent = log.copy()
            recent["date"] = pd.to_datetime(recent["date"])
            events = recent[recent["date"] == last].to_dict(orient="records")
        meta_events = events
    elif m == "strong":
        strong_w = strong_leader_weights(closes, bench_close, config=cfg)
        row = strong_w.loc[last]
        active = row[row.abs() > 1e-12]
        if len(active):
            target_raw = {str(active.index[0]): float(active.iloc[0])}
        meta_events = []
    else:
        meta_events = []

    row = meta_df.loc[last]
    meta = {
        "asof": str(last.date()),
        "preset": "v8",
        "rule": "structure_gate_v8",
        "mode": m,
        "book": book_name(),
        "bench": bench_sym,
        "target_raw": target_raw,
        "sticky": bool(row.get("sticky", 0)),
        "thrust": bool(row.get("thrust", 0)),
        "mild": bool(row.get("mild", 0)),
        "harsh_ret": bool(row.get("harsh_ret", 0)),
        "harsh_dd": bool(row.get("harsh_dd", 0)),
        "index_lean": bool(row.get("index_lean", 0)),
        "stock_led": bool(row.get("stock_led", 0)),
        "crowded": bool(row.get("crowded", 0)),
        "events_today": meta_events if m == "ers" else [],
    }
    return target_raw, meta


def to_lb_targets(target_raw: dict[str, float]) -> dict[str, float]:
    return {normalize_symbol(f"{s}.US"): float(w) for s, w in target_raw.items()}


def marks_from_panel(frames: dict[str, pd.DataFrame], symbols_lb: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for lb in symbols_lb:
        bare = lb.split(".")[0]
        df = frames.get(bare)
        if df is None or df.empty:
            continue
        out[lb] = float(df["close"].iloc[-1])
    return out


def sleeve_equity(broker: LongbridgeBrokerAdapter, marks: dict[str, float]) -> float:
    cash = float(broker.get_cash())
    pos = broker.get_positions()
    mtm = 0.0
    for sym, qty in pos.items():
        px = marks.get(sym) or marks.get(sym.upper())
        if px is None:
            continue
        mtm += float(qty) * float(px)
    eq = cash + mtm
    cap = _env_float("QRESEARCH_SLEEVE_USD", None)
    if cap is not None and cap > 0:
        return min(eq, float(cap))
    return eq


def already_ran_today(state_path: Path, asof: str) -> bool:
    if not state_path.is_file():
        return False
    try:
        st = json.loads(state_path.read_text())
    except Exception:
        return False
    return st.get("asof") == asof and bool(st.get("submitted"))


def assert_paper_only_submit(submit: bool) -> None:
    """Refuse venue submit unless paper-only guard is on."""
    if not submit:
        return
    if not _env_bool("QRESEARCH_SG_PAPER_ONLY", True):
        raise SystemExit(
            "REFUSE: QRESEARCH_SG_PAPER_ONLY=0 — Structure Gate will not submit. "
            "Paper trade only."
        )
    # Soft hint: allow override marker for operators who know token is paper.
    allow = _env_bool("QRESEARCH_SG_PAPER_SUBMIT", False)
    if not allow:
        raise SystemExit("REFUSE: set QRESEARCH_SG_PAPER_SUBMIT=1 for paper submit")


def run_backtest(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    bench_open: pd.Series,
    bench_close: pd.Series,
    *,
    bench_volume: pd.Series | None,
    base: Path,
    book: str,
    bench_sym: str,
) -> int:
    cfg = StructureGateConfig.v8()
    start = pd.Timestamp(os.getenv("QRESEARCH_SG_BT_START", "2025-01-01"))
    end_raw = os.getenv("QRESEARCH_SG_BT_END", "").strip()
    if end_raw:
        end = pd.Timestamp(end_raw)
        opens = opens.loc[:end]
        closes = closes.loc[:end]
        bench_open = bench_open.loc[:end]
        bench_close = bench_close.loc[:end]
        if bench_volume is not None:
            bench_volume = bench_volume.loc[:end]

    fees = FutuUsEquityFees(slippage_bps=cfg.bench_slippage_bps)
    stock_fees = fees.with_slippage(cfg.stock_slippage_bps)
    sim = simulate_structure_gate(
        opens,
        closes,
        bench_open,
        bench_close,
        capital=CAPITAL,
        start=start,
        fees=fees,
        config=cfg,
        bench_volume=bench_volume,
    )
    eq = sim.equity
    win = eq.index
    eq_bh = simulate_bench_bh(
        bench_open, bench_close, capital=CAPITAL, start=start, fees=fees
    ).reindex(win).ffill()
    eq_cash = simulate_cash(capital=CAPITAL, index=win)

    def _tot(s: pd.Series) -> float:
        s = s.dropna()
        if len(s) < 2:
            return 0.0
        return float(s.iloc[-1] / s.iloc[0] - 1.0)

    sw_ret = _tot(eq)
    bh_ret = _tot(eq_bh)
    ers_book = EmergingRSWaveBook(gate="G1", config=cfg.ers_config or EmergingRSWaveConfig())
    decision, _ = ers_book.generate_weights(closes, bench_close)
    try:
        eq_ers, _ = simulate_book(
            opens.loc[win], closes.loc[win], decision.loc[win], CAPITAL, stock_fees
        )
        ers_ret = _tot(eq_ers)
    except Exception as exc:  # noqa: BLE001
        print(f"pure ers baseline skipped: {exc}")
        ers_ret = float("nan")

    gate = soft_pass(sw_ret, bh_ret, ers_ret if pd.notna(ers_ret) else bh_ret)
    dist = sim.mode.reindex(win).dropna().value_counts(normalize=True)
    out = base / "backtest"
    eq.to_csv(out / "equity_structure_gate.csv", header=["equity"])
    eq_bh.to_csv(out / "equity_bench_bh.csv", header=["equity"])
    eq_cash.to_csv(out / "equity_cash.csv", header=["equity"])
    sim.mode.to_csv(out / "modes.csv", header=["mode"])
    if len(sim.trades):
        sim.trades.to_csv(out / "trades.csv", index=False)
    summary = {
        "ok": True,
        "preset": "v8",
        "book": book,
        "bench": bench_sym,
        "source": "longbridge",
        "start": str(start.date()),
        "end": str(eq.index.max().date()) if len(eq) else None,
        "capital": CAPITAL,
        "structure_gate_total_return": sw_ret,
        "bench_bh_total_return": bh_ret,
        "pure_ers_total_return": ers_ret if pd.notna(ers_ret) else None,
        "mode_distribution": dist.to_dict(),
        "soft_pass": gate.get("soft_pass"),
        "hard_pass_beat_both": gate.get("hard_pass_beat_both"),
        "n_trades": int(len(sim.trades)),
        "generated_at_utc": str(pd.Timestamp.now("UTC").tz_localize(None)),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=float) + "\n")
    (base / "latest_backtest.json").write_text(json.dumps(summary, indent=2, default=float) + "\n")
    print(
        f"backtest book={book} {start.date()}→{summary['end']} "
        f"SG={sw_ret*100:.1f}% BH={bh_ret*100:.1f}% soft={gate.get('soft_pass')} "
        f"→ {out / 'summary.json'}"
    )
    return 0


def main() -> int:
    load_dotenv_if_present(ROOT / ".env")
    if not has_longbridge_credentials():
        print("Missing Longbridge credentials (.env / env vars).")
        return 2

    mode = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("QRESEARCH_SG_PAPER_MODE", "once")).lower()
    if mode not in {"signal", "once", "backtest"}:
        print(f"unknown mode={mode}; use signal|once|backtest")
        return 2

    submit = _env_bool("QRESEARCH_SG_PAPER_SUBMIT", False)
    force = _env_bool("QRESEARCH_FORCE", False)
    book = book_name()
    bench_sym, members = resolve_universe(book)

    base = out_dir()
    cache = base / "cache_ohlcv"
    state_path = base / "state.json"
    ts = pd.Timestamp.now("UTC").tz_localize(None)

    print(f"mode={mode} submit={submit} book={book} bench={bench_sym} out={base}")
    print("paper_only=1 — Structure Gate submits only to Longbridge paper")

    want = [bench_sym, *members]
    print(f"loading {len(want)} symbols from Longbridge…")
    frames = load_panel(want, cache)
    opens, closes, bench_open, bench_close, bench_vol = build_closes(frames, bench_sym)
    print(f"usable_members={len(closes.columns)}")

    if mode == "backtest":
        return run_backtest(
            opens,
            closes,
            bench_open,
            bench_close,
            bench_volume=bench_vol,
            base=base,
            book=book,
            bench_sym=bench_sym,
        )

    cfg = StructureGateConfig.v8()
    target_raw, meta = latest_target(
        closes, bench_close, bench_sym, bench_volume=bench_vol, cfg=cfg
    )
    target = to_lb_targets(target_raw)
    asof = meta["asof"]

    # Venue reads always ok; orders only when submit + paper-only guard.
    broker = LongbridgeBrokerAdapter.from_env(
        dry_run=not submit,
        currency=os.getenv("QRESEARCH_LB_CURRENCY", "USD"),
        default_market="US",
    )
    positions = broker.get_positions()
    need_marks = sorted(set(positions) | set(target) | {f"{bench_sym}.US"})
    marks = marks_from_panel(frames, need_marks)
    if broker.quote_ctx is not None and need_marks:
        try:
            for q in broker.quote_ctx.quote(need_marks):
                last = getattr(q, "last_done", None)
                if last is not None and float(last) > 0:
                    marks[normalize_symbol(q.symbol)] = float(last)
        except Exception as exc:  # noqa: BLE001
            print(f"quote overlay skipped: {exc}")

    eq = sleeve_equity(broker, marks)
    plan = {
        **meta,
        "job_mode": mode,
        "submit": submit,
        "paper_only": True,
        "positions": positions,
        "target": target,
        "marks": marks,
        "sleeve_equity_usd": eq,
        "cash_usd": broker.get_cash(),
        "generated_at_utc": str(ts),
    }

    preview_broker = LongbridgeBrokerAdapter(
        dry_run=True,
        currency="USD",
        default_market="US",
        initial_cash=eq,
    )
    preview_broker._local_cash = float(broker.get_cash())  # noqa: SLF001
    preview_broker._local_positions = dict(positions)  # noqa: SLF001
    try:
        preview_fills = TargetWeightExecutor(preview_broker, min_trade_notional=25.0).rebalance(
            target, marks, ts, equity=eq
        )
        plan["preview_orders"] = [
            {
                "order_id": f.order_id,
                "symbol": f.symbol,
                "side": f.side.value if hasattr(f.side, "value") else str(f.side),
                "quantity": f.quantity,
                "price": f.price,
            }
            for f in preview_fills
        ]
    except Exception as exc:  # noqa: BLE001
        plan["preview_orders"] = []
        plan["preview_error"] = str(exc)

    signal_path = base / f"signal_{asof}.json"
    latest_path = base / "latest_signal.json"
    signal_path.write_text(json.dumps(plan, indent=2, default=float) + "\n")
    latest_path.write_text(json.dumps(plan, indent=2, default=float) + "\n")

    held = ", ".join(f"{k}:{v:g}" for k, v in positions.items()) or "(flat)"
    tgt = ", ".join(f"{k}:{v:.0%}" for k, v in target.items()) or "(flat)"
    print(f"asof={asof} mode={meta['mode']}")
    print(f"positions={held}")
    print(f"target={tgt}")
    print(f"sleeve_equity_usd={eq:,.2f}")
    print(f"preview_orders={len(plan.get('preview_orders') or [])}")
    for o in plan.get("preview_orders") or []:
        print(f"  {o['side']} {o['quantity']:g} {o['symbol']} @~{o['price']}")

    if mode == "signal":
        print(f"wrote {latest_path} (signal only)")
        return 0

    if not submit:
        print(
            "SUBMIT=0 — plan only, no venue orders. "
            "Set QRESEARCH_SG_PAPER_SUBMIT=1 to paper-trade."
        )
        state_path.write_text(
            json.dumps({"asof": asof, "submitted": False, "at": str(ts)}, indent=2) + "\n"
        )
        return 0

    try:
        assert_paper_only_submit(True)
    except SystemExit as exc:
        print(str(exc))
        return 3

    if already_ran_today(state_path, asof) and not force:
        print(f"already submitted for asof={asof}; set QRESEARCH_FORCE=1 to override")
        return 0

    # Re-bind broker with dry_run=False only after paper-only assert.
    live_broker = LongbridgeBrokerAdapter.from_env(
        dry_run=False,
        currency=os.getenv("QRESEARCH_LB_CURRENCY", "USD"),
        default_market="US",
    )
    fills = TargetWeightExecutor(live_broker, min_trade_notional=25.0).rebalance(
        target, marks, ts, equity=eq
    )
    fill_rows = [
        {
            "order_id": f.order_id,
            "symbol": f.symbol,
            "side": f.side.value if hasattr(f.side, "value") else str(f.side),
            "quantity": f.quantity,
            "price": f.price,
            "fee": f.fee,
            "timestamp": str(f.timestamp),
        }
        for f in fills
    ]
    result = {
        **plan,
        "fills": fill_rows,
        "positions_after": live_broker.get_positions(),
        "cash_after": live_broker.get_cash(),
    }
    log_path = base / "logs" / f"run_{ts.strftime('%Y%m%dT%H%M%S')}.json"
    log_path.write_text(json.dumps(result, indent=2, default=float) + "\n")
    (base / "latest_run.json").write_text(json.dumps(result, indent=2, default=float) + "\n")
    state_path.write_text(
        json.dumps(
            {
                "asof": asof,
                "submitted": True,
                "paper_only": True,
                "at": str(ts),
                "n_fills": len(fills),
                "mode": meta["mode"],
            },
            indent=2,
        )
        + "\n"
    )
    print(f"paper submitted fills={len(fills)} → {log_path}")
    for row in fill_rows:
        print(f"  FILL {row['side']} {row['quantity']:g} {row['symbol']} @ {row['price']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
