#!/usr/bin/env python3
"""Daily Emerging RS G1 paper-trade job for VPS cron + Longbridge.

Default is plan-only (no orders). Set QRESEARCH_LB_SUBMIT=1 to send market
orders to the Longbridge account (your token is currently paper trading).

Typical cron (America/New_York):
  # After US close — write signal / optional submit
  30 16 * * 1-5  /opt/qresearch/deploy/vps-cron/run.sh once
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

from qresearch.brokers.longbridge import LongbridgeBrokerAdapter, has_longbridge_credentials
from qresearch.brokers.longbridge.config import load_dotenv_if_present, load_longbridge_config
from qresearch.brokers.longbridge.history import candlesticks_to_ohlcv
from qresearch.brokers.longbridge.symbols import normalize_symbol
from qresearch.data.loader import validate_ohlcv
from qresearch.execution.targets import TargetWeightExecutor
from qresearch.strategy.emerging_rs_wave import EmergingRSWaveBook, market_gate

from run_emerging_rs_wave_gates import UNIVERSE  # type: ignore

GATE = "G1"
MIN_BARS = 220
WARM_START = date(2023, 1, 1)
DEFAULT_OUT = ROOT / "examples" / "data" / "emerging_rs_g1_paper"


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
    path = Path(os.getenv("QRESEARCH_PAPER_OUT", str(DEFAULT_OUT)))
    path.mkdir(parents=True, exist_ok=True)
    (path / "cache_ohlcv").mkdir(parents=True, exist_ok=True)
    (path / "logs").mkdir(parents=True, exist_ok=True)
    return path


def load_cache(cache: Path, symbol: str) -> pd.DataFrame | None:
    path = cache / f"{symbol}.csv"
    if not path.is_file() or path.stat().st_size < 64:
        return None
    try:
        raw = pd.read_csv(path, index_col=0, parse_dates=True)
    except Exception:
        return None
    raw.columns = [str(c).lower() for c in raw.columns]
    need = ["open", "high", "low", "close", "volume"]
    if any(c not in raw.columns for c in need):
        return None
    try:
        df = validate_ohlcv(raw[need].dropna())
    except ValueError:
        return None
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    if len(df) < MIN_BARS:
        return None
    return df[~df.index.duplicated(keep="last")].sort_index()


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
    try:
        for i, sym in enumerate(symbols, 1):
            cached = None if refresh else load_cache(cache, sym)
            if cached is not None and cached.index.max().date() >= date.today() - timedelta(days=3):
                frames[sym] = cached
                continue
            # Prefer refresh; fall back to stale cache if fetch fails.
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
    finally:
        pass
    return frames


def latest_target(closes: pd.DataFrame, bench: pd.Series) -> tuple[dict[str, float], dict]:
    book = EmergingRSWaveBook(gate=GATE)
    weights, log = book.generate_weights(closes, bench)
    last = closes.index.max()
    row = weights.loc[last]
    active = row[row.abs() > 1e-12]
    target_raw = {str(active.index[0]): float(active.iloc[0])} if len(active) else {}
    gate_on = bool(market_gate(bench, GATE).loc[last])
    meta = {
        "asof": str(last.date()),
        "gate": GATE,
        "gate_open": gate_on,
        "target_raw": target_raw,
        "n_events": int(len(log)),
    }
    if len(log):
        recent = log.copy()
        recent["date"] = pd.to_datetime(recent["date"])
        last_ev = recent[recent["date"] == last]
        meta["events_today"] = last_ev.to_dict(orient="records")
    else:
        meta["events_today"] = []
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
    """USD sleeve for sizing; optional cap via QRESEARCH_SLEEVE_USD."""
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


def main() -> int:
    load_dotenv_if_present(ROOT / ".env")
    if not has_longbridge_credentials():
        print("Missing Longbridge credentials (.env / env vars).")
        return 2

    mode = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("QRESEARCH_PAPER_MODE", "once")).lower()
    submit = _env_bool("QRESEARCH_LB_SUBMIT", False)
    force = _env_bool("QRESEARCH_FORCE", False)

    base = out_dir()
    cache = base / "cache_ohlcv"
    state_path = base / "state.json"
    ts = pd.Timestamp.now("UTC").tz_localize(None)

    print(f"mode={mode} submit={submit} out={base}")
    want = ["QQQ", *list(UNIVERSE)]
    print(f"loading {len(want)} symbols from Longbridge…")
    frames = load_panel(want, cache)
    if "QQQ" not in frames:
        print("QQQ history failed")
        return 1

    qqq = frames["QQQ"]
    stock = {s: df for s, df in frames.items() if s != "QQQ"}
    idx = qqq.index
    closes = pd.DataFrame({s: stock[s]["close"].reindex(idx) for s in stock})
    keep = [c for c in closes.columns if closes[c].notna().sum() >= MIN_BARS]
    closes = closes[keep]
    print(f"usable={len(keep)}")

    target_raw, meta = latest_target(closes, qqq["close"])
    target = to_lb_targets(target_raw)
    asof = meta["asof"]

    broker = LongbridgeBrokerAdapter.from_env(
        dry_run=not submit,
        currency=os.getenv("QRESEARCH_LB_CURRENCY", "USD"),
        default_market="US",
    )
    positions = broker.get_positions()
    # Marks for held + target names
    need_marks = sorted(set(positions) | set(target) | {"QQQ.US"})
    marks = marks_from_panel(frames, need_marks)
    # Live quotes override last close when available
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
        "mode": mode,
        "submit": submit,
        "positions": positions,
        "target": target,
        "marks": marks,
        "sleeve_equity_usd": eq,
        "cash_usd": broker.get_cash(),
        "generated_at_utc": str(ts),
    }

    # Preview orders without requiring submit
    preview_broker = LongbridgeBrokerAdapter(
        dry_run=True,
        currency="USD",
        default_market="US",
        initial_cash=eq,
    )
    # Seed local ledger from venue positions for preview sizing
    preview_broker._local_cash = float(broker.get_cash())  # noqa: SLF001
    preview_broker._local_positions = dict(positions)  # noqa: SLF001
    # Cap preview equity via executor equity= arg
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
    print(f"asof={asof} gate_open={meta['gate_open']}")
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
        print("SUBMIT=0 — plan only, no venue orders. Set QRESEARCH_LB_SUBMIT=1 to paper-trade.")
        state_path.write_text(
            json.dumps({"asof": asof, "submitted": False, "at": str(ts)}, indent=2) + "\n"
        )
        return 0

    if already_ran_today(state_path, asof) and not force:
        print(f"already submitted for asof={asof}; set QRESEARCH_FORCE=1 to override")
        return 0

    fills = TargetWeightExecutor(broker, min_trade_notional=25.0).rebalance(
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
        "positions_after": broker.get_positions(),
        "cash_after": broker.get_cash(),
    }
    log_path = base / "logs" / f"run_{ts.strftime('%Y%m%dT%H%M%S')}.json"
    log_path.write_text(json.dumps(result, indent=2, default=float) + "\n")
    (base / "latest_run.json").write_text(json.dumps(result, indent=2, default=float) + "\n")
    state_path.write_text(
        json.dumps({"asof": asof, "submitted": True, "at": str(ts), "n_fills": len(fills)}, indent=2)
        + "\n"
    )
    print(f"submitted fills={len(fills)} → {log_path}")
    for row in fill_rows:
        print(f"  FILL {row['side']} {row['quantity']:g} {row['symbol']} @ {row['price']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
