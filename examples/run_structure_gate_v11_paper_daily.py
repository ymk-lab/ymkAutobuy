#!/usr/bin/env python3
"""Structure Gate v11 paper job: Futu OpenD (SIMULATE) + 40/30/30 sleeves.

SPY 40% / QQQ 30% / SMH 30% each run Structure Gate independently; merged
target weights are sent to one Futu paper account.

Schedule (America/New_York):
  - ``signal`` after cash close (~16:30): compute targets only
  - ``once`` at **09:40** next session: submit (official fill window; not 09:30)

Safety:
  - Default dry-run; submit only with QRESEARCH_SG_PAPER_SUBMIT=1
  - FUTU_TRD_ENV defaults to SIMULATE (paper)
  - Refuses REAL unless QRESEARCH_FUTU_ALLOW_LIVE=1
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from qresearch.brokers.futu import FutuBrokerAdapter, has_futu_opend, load_dotenv_if_present
from qresearch.brokers.futu.symbols import normalize_symbol
from qresearch.data.loader import validate_ohlcv
from qresearch.execution.targets import TargetWeightExecutor
from qresearch.paper.fill_audit import append_fills_ledger, reconcile_fills, write_audit
from qresearch.strategy.structure_gate import V11_BOOK_WEIGHTS, StructureGateConfig
from run_emerging_rs_wave_gates import UNIVERSE as QQQ_UNIVERSE  # type: ignore
from run_emerging_rs_wave_soxx import UNIVERSE as SEMI_UNIVERSE  # type: ignore
from run_structure_gate_v8_paper_daily import (  # type: ignore
    MIN_BARS,
    latest_target,
    load_cache,
    save_cache,
)


def _configure_stdio() -> None:
    """Avoid Windows cp950 crashes on Futu Chinese error strings."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def _safe(text: object) -> str:
    s = str(text)
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        return s.encode(enc, errors="replace").decode(enc, errors="replace")
    except Exception:
        return s.encode("ascii", errors="replace").decode("ascii")


def log(msg: object = "") -> None:
    print(_safe(msg), flush=True)

DEFAULT_OUT = ROOT / "examples" / "data" / "structure_gate_v11_paper"
WEIGHTS = dict(V11_BOOK_WEIGHTS)
CACHE_FALLBACKS = [
    ROOT / "examples/data/structure_gate_v8_paper/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_qqq_g1_longbridge/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_smh/cache_ohlcv",
    ROOT / "examples/data/emerging_rs_wave_spy/cache_ohlcv",
]


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
    return path


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


def load_symbol_any(cache: Path, symbol: str) -> pd.DataFrame | None:
    df = load_cache(cache, symbol)
    if df is not None:
        return df
    for fb in CACHE_FALLBACKS:
        df = load_cache(fb, symbol)
        if df is not None:
            save_cache(cache, symbol, df)
            return df
    return None


def refresh_via_futu(symbols: list[str], cache: Path) -> int:
    if not has_futu_opend():
        log("OpenD not reachable — skip Futu history refresh")
        return 0
    from futu import OpenQuoteContext

    from qresearch.brokers.futu.config import futu_opend_host, futu_opend_port
    from qresearch.brokers.futu.history import fetch_daily_resilient
    from qresearch.brokers.futu.symbols import to_futu_code

    host, port = futu_opend_host(), futu_opend_port()
    ctx = OpenQuoteContext(host=host, port=port)
    n_ok = 0
    try:
        for i, sym in enumerate(symbols, 1):
            df, note = fetch_daily_resilient(
                ctx, sym, start=date(2021, 6, 1), min_bars=MIN_BARS
            )
            if df is None or len(df) == 0:
                if i <= 3 or sym in {"SPY", "QQQ", "SMH"}:
                    log(f"futu miss {sym} ({to_futu_code(sym)}): {note}")
                continue
            # Merge with existing cache so a shorter Futu window still advances asof.
            old = load_cache(cache, sym)
            if old is not None and len(old):
                merged = pd.concat([old, df]).sort_index()
                merged = merged[~merged.index.duplicated(keep="last")]
                df = merged
            if len(df) < MIN_BARS:
                if i <= 3 or sym in {"SPY", "QQQ", "SMH"}:
                    log(
                        f"futu short {sym} ({to_futu_code(sym)}): bars={len(df)} "
                        f"need>={MIN_BARS} ({note}); keep for yfinance merge"
                    )
                save_cache(cache, sym, df)
                continue
            save_cache(cache, sym, df)
            n_ok += 1
            if i == 1 or i % 40 == 0 or i == len(symbols) or sym in {"SPY", "QQQ", "SMH"}:
                log(
                    f"futu [{i}/{len(symbols)}] ok={n_ok} last={sym} "
                    f"bars={len(df)} {note}"
                )
    finally:
        ctx.close()
    return n_ok


def bootstrap_via_yfinance(symbols: list[str], cache: Path) -> int:
    """Fill missing OHLCV from Yahoo when Futu history is unavailable."""
    try:
        import yfinance as yf
    except ImportError:
        log("yfinance not installed — pip install yfinance")
        return 0

    n_ok = 0
    for i, sym in enumerate(symbols, 1):
        if load_cache(cache, sym) is not None:
            continue
        try:
            raw = yf.download(
                sym,
                start="2021-06-01",
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if raw is None or len(raw) < MIN_BARS:
                log(f"yf miss {sym}: rows={0 if raw is None else len(raw)}")
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = [str(c[0]).lower() for c in raw.columns]
            else:
                raw.columns = [str(c).lower() for c in raw.columns]
            need = ["open", "high", "low", "close", "volume"]
            if any(c not in raw.columns for c in need):
                log(f"yf miss {sym}: bad columns {list(raw.columns)}")
                continue
            df = validate_ohlcv(raw[need].dropna())
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            df = df[~df.index.duplicated(keep="last")].sort_index()
            if len(df) < MIN_BARS:
                continue
            save_cache(cache, sym, df)
            n_ok += 1
            if i == 1 or i % 40 == 0 or i == len(symbols) or sym in {"SPY", "QQQ", "SMH"}:
                log(f"yf [{i}/{len(symbols)}] ok={n_ok} last={sym} bars={len(df)}")
        except Exception as exc:  # noqa: BLE001
            log(f"yf miss {sym}: {exc}")
    return n_ok


def _skip_path(cache: Path, symbol: str) -> Path:
    return cache / f"{symbol}.skip"


def _cache_last_date(cache: Path, sym: str) -> date | None:
    df = load_cache(cache, sym)
    if df is None or len(df) == 0:
        return None
    try:
        return pd.Timestamp(df.index.max()).date()
    except Exception:
        return None


def _refresh_symbol_yfinance(cache: Path, sym: str) -> bool:
    try:
        import yfinance as yf
    except ImportError:
        log("yfinance not installed — pip install yfinance")
        return False
    try:
        raw = yf.download(
            sym,
            start="2021-06-01",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        if raw is None or len(raw) < MIN_BARS:
            return False
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [str(c[0]).lower() for c in raw.columns]
        else:
            raw.columns = [str(c).lower() for c in raw.columns]
        df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        df = df[~df.index.duplicated(keep="last")].sort_index()
        if len(df) < MIN_BARS:
            return False
        save_cache(cache, sym, df)
        log(f"yf refresh {sym} bars={len(df)} last={df.index.max().date()}")
        return True
    except Exception as exc:  # noqa: BLE001
        log(f"yf refresh {sym}: {exc}")
        return False


def ensure_market_data(cache: Path, *, refresh: bool) -> None:
    """Ensure sleeve benches stay current; bootstrap missing members once.

    A warm cache used to skip *all* history refresh, so ``asof`` could stick on
    an old session and the next ``once`` cron would no-op (already submitted).
    """
    from datetime import timedelta

    benches = ["SPY", "QQQ", "SMH"]
    light = sorted(set(benches) | set(book_members("QQQ")) | set(book_members("SMH")))
    cache.mkdir(parents=True, exist_ok=True)

    def _needed(sym: str) -> bool:
        if load_cache(cache, sym) is not None:
            return False
        if _skip_path(cache, sym).is_file() and sym not in benches:
            return False
        return True

    missing = [s for s in light if _needed(s)]
    force = _env_bool("QRESEARCH_FORCE_REFRESH", False)
    today = date.today()
    # Benches older than 3 calendar days are always stale (covers long weekends).
    # On weekdays, also refresh if last bar is before yesterday.
    stale_cutoff = today - timedelta(days=3 if today.weekday() >= 5 else 1)
    stale_benches = [
        b
        for b in benches
        if (refresh or force)
        and ((_cache_last_date(cache, b) or date(1970, 1, 1)) < stale_cutoff)
    ]

    if not missing and not force and not stale_benches:
        lasts = {b: str(_cache_last_date(cache, b)) for b in benches}
        log(f"cache warm — benches fresh {lasts}; skip bulk refresh")
        return

    want_futu = list(dict.fromkeys([*stale_benches, *(light if force else missing)]))
    if want_futu:
        log(
            f"refresh futu n={len(want_futu)} stale_benches={stale_benches} "
            f"missing={len(missing)} force={int(force)}"
        )
        n_futu = refresh_via_futu(want_futu, cache)
        log(f"futu refreshed ok={n_futu}")

    # Yahoo fallback for still-missing members and still-stale benches.
    still_missing = [s for s in light if _needed(s)]
    still_stale = [
        b
        for b in benches
        if (refresh or force)
        and ((_cache_last_date(cache, b) or date(1970, 1, 1)) < stale_cutoff)
    ]
    for sym in list(dict.fromkeys([*still_stale, *still_missing])):
        if sym in still_stale or load_cache(cache, sym) is None:
            _refresh_symbol_yfinance(cache, sym)

    for sym in light:
        if sym in benches:
            continue
        if load_cache(cache, sym) is None and not _skip_path(cache, sym).is_file():
            _skip_path(cache, sym).write_text("skip\n", encoding="utf-8")


def build_book_panel(
    frames: dict[str, pd.DataFrame], book: str
) -> tuple[pd.DataFrame, pd.Series, pd.Series | None]:
    if book not in frames:
        raise SystemExit(f"bench {book} missing")
    bdf = frames[book]
    idx = bdf.index
    members = [s for s in book_members(book) if s in frames and s != book]
    closes = pd.DataFrame({s: frames[s]["close"].reindex(idx) for s in members}, index=idx)
    keep = [c for c in closes.columns if closes[c].notna().sum() >= MIN_BARS]
    closes = closes[keep]
    # Empty stock panel is OK (mode can still be cash/bench from index alone).
    if closes.shape[1] == 0:
        closes = pd.DataFrame(index=idx)
    vol = bdf["volume"] if "volume" in bdf.columns else None
    return closes, bdf["close"], vol


def merge_targets(book_targets: dict[str, dict[str, float]], weights: dict[str, float]) -> dict[str, float]:
    merged: dict[str, float] = {}
    for book, w in weights.items():
        for sym, tw in (book_targets.get(book) or {}).items():
            lb = normalize_symbol(f"{sym}.US" if "." not in sym else sym)
            merged[lb] = merged.get(lb, 0.0) + float(w) * float(tw)
    # drop dust
    return {k: v for k, v in merged.items() if abs(v) > 1e-6}



def write_paper_state(
    state_path: Path,
    *,
    asof: str,
    submitted: bool,
    ts: object,
    preset: str,
    extra: dict | None = None,
) -> None:
    """Persist paper state without wiping a prior successful submit for same asof."""
    prev: dict = {}
    if state_path.is_file():
        try:
            prev = json.loads(state_path.read_text())
        except Exception:
            prev = {}
    keep_submitted = bool(prev.get("submitted")) and str(prev.get("asof")) == str(asof)
    payload = {
        "asof": asof,
        "submitted": bool(submitted) or keep_submitted,
        "at": str(ts),
        "preset": preset,
    }
    if keep_submitted and not submitted:
        # Preserve prior submit metadata when signal/dry-run refreshes the plan.
        for k in ("paper_only", "broker", "n_fills", "fill_audit"):
            if k in prev:
                payload[k] = prev[k]
        payload["plan_refreshed_at"] = str(ts)
        payload["at"] = str(prev.get("at") or ts)
    if extra:
        payload.update(extra)
    state_path.write_text(json.dumps(payload, indent=2, default=float) + "\n")

def already_ran_today(state_path: Path, asof: str) -> bool:
    if not state_path.is_file():
        return False
    try:
        st = json.loads(state_path.read_text())
    except Exception:
        return False
    return st.get("asof") == asof and bool(st.get("submitted"))


def _research_cost_usd(quantity: float, price: float, *, slippage_bps: float) -> dict[str, float]:
    """Match backtest ``FutuUsEquityFees.total_cost_usd`` (broker + slippage)."""
    from qresearch.backtest.futu_costs import FutuUsEquityFees

    px = float(price)
    qty = abs(float(quantity))
    notional = qty * px
    model = FutuUsEquityFees(slippage_bps=float(slippage_bps))
    broker = float(model.broker_fee_usd(qty, notional))
    slip = float(notional * (float(slippage_bps) / 10_000.0))
    total = float(model.total_cost_usd(notional, px))
    return {
        "broker_fee_usd": broker,
        "slippage_usd": slip,
        "slippage_bps": float(slippage_bps),
        "research_cost_usd": total,
    }


def _annotate_fill_costs(
    rows: list[dict],
    *,
    slippage_bps: float,
) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        r = dict(row)
        costs = _research_cost_usd(
            float(r.get("quantity") or 0.0),
            float(r.get("price") or 0.0),
            slippage_bps=slippage_bps,
        )
        r.update(costs)
        # Paper audit / ledger: use research total when broker reported 0.
        reported = float(r.get("fee") or 0.0)
        r["fee_broker_reported"] = reported
        r["fee"] = max(reported, costs["research_cost_usd"])
        out.append(r)
    return out


def main() -> int:
    _configure_stdio()
    load_dotenv_if_present(ROOT / ".env")
    mode = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("QRESEARCH_SG_PAPER_MODE", "once")).lower()
    if mode not in {"signal", "once"}:
        log("use signal|once")
        return 2

    submit = _env_bool("QRESEARCH_SG_PAPER_SUBMIT", False)
    force = _env_bool("QRESEARCH_FORCE", False)
    if submit and not _env_bool("QRESEARCH_SG_PAPER_ONLY", True):
        log("REFUSE: QRESEARCH_SG_PAPER_ONLY=0")
        return 3

    base = out_dir()
    cache = base / "cache_ohlcv"
    state_path = base / "state.json"
    ts = pd.Timestamp.now("UTC").tz_localize(None)
    cfg = StructureGateConfig.v11()

    log(f"mode={mode} submit={submit} weights={WEIGHTS} broker=futu out={base}")
    log(f"opend={has_futu_opend()} simulate=1 paper_only=1")

    want = sorted(
        {"SPY", "QQQ", "SMH"}
        | set(book_members("QQQ"))
        | set(book_members("SMH"))
        | set(book_members("SPY"))
    )
    # First local run often has empty cache (lean package). Fill via Futu, else Yahoo.
    refresh = _env_bool("QRESEARCH_REFRESH_CACHE", True)
    ensure_market_data(cache, refresh=refresh)

    frames: dict[str, pd.DataFrame] = {}
    for sym in want:
        df = load_symbol_any(cache, sym)
        if df is not None:
            frames[sym] = df
    for b in WEIGHTS:
        if b not in frames:
            log(f"missing bench cache {b}")
            log("hint: pip install yfinance  then re-run; or check OpenD US quote rights")
            return 1
    log(f"frames={len(frames)} benches=OK")

    book_meta = {}
    book_targets_raw: dict[str, dict[str, float]] = {}
    asof = None
    for book in WEIGHTS:
        closes, bench_close, bench_vol = build_book_panel(frames, book)
        raw, meta = latest_target(
            closes, bench_close, book, bench_volume=bench_vol, cfg=cfg
        )
        book_targets_raw[book] = raw
        book_meta[book] = meta
        asof = meta["asof"]
        tgt = ", ".join(f"{k}:{v:.0%}" for k, v in raw.items()) or "(flat)"
        log(f"  {book}: mode={meta['mode']} target={tgt} members={len(closes.columns)}")

    target = merge_targets(book_targets_raw, WEIGHTS)
    log(
        "merged_target= "
        + (", ".join(f"{k}:{v:.1%}" for k, v in target.items()) or "(flat)")
    )

    # Broker
    broker: FutuBrokerAdapter
    if has_futu_opend():
        broker = FutuBrokerAdapter.from_opend(
            dry_run=not submit,
            currency=os.getenv("QRESEARCH_LB_CURRENCY", "USD"),
            default_market="US",
            simulate=True,
        )
    else:
        log("WARN: OpenD down — dry-run local ledger only")
        broker = FutuBrokerAdapter(dry_run=True, simulate=True, initial_cash=_env_float("QRESEARCH_SLEEVE_USD", 50_000.0) or 50_000.0)

    try:
        positions = broker.get_positions()
        need_marks = sorted(set(positions) | set(target) | {"SPY.US", "QQQ.US", "SMH.US"})
        marks: dict[str, float] = {}
        mark_source = "daily_close"
        for lb in need_marks:
            bare = lb.split(".")[0]
            df = frames.get(bare)
            if df is not None and len(df):
                marks[lb] = float(df["close"].iloc[-1])
        if broker.quote_ctx is not None:
            try:
                snap = broker.snapshot_quotes(need_marks)
                if snap:
                    marks.update(snap)
                    mark_source = "snapshot"
            except Exception as exc:  # noqa: BLE001
                log(f"snapshot skipped: {exc}")

        # Official live fill window is 09:40 ET — prefer that bar open for once/submit.
        if mode == "once":
            try:
                from qresearch.brokers.futu.intraday import resolve_0940_marks

                m0940, src0940 = resolve_0940_marks(
                    need_marks,
                    quote_ctx=getattr(broker, "quote_ctx", None),
                    day=datetime.now(ZoneInfo("America/New_York")).date(),
                )
                if m0940:
                    marks.update(m0940)
                    mark_source = src0940
                    log(
                        f"marks_0940 source={src0940} n={len(m0940)} "
                        + ", ".join(f"{k}={v:.4f}" for k, v in sorted(m0940.items())[:6])
                    )
                else:
                    log("marks_0940 unavailable — keeping snapshot/close")
            except Exception as exc:  # noqa: BLE001
                log(f"marks_0940 failed: {exc}")

        cash = broker.get_cash()
        eq = broker.get_equity(marks)
        cap = _env_float("QRESEARCH_SLEEVE_USD", None)
        if cap is not None and cap > 0:
            eq = min(eq, cap)

        plan = {
            "asof": asof,
            "preset": "v11",
            "rule": "structure_gate_v11_blend",
            "broker": "futu",
            "weights": WEIGHTS,
            "books": book_meta,
            "target_raw_by_book": book_targets_raw,
            "target": target,
            "mode": "blend",
            "submit": submit,
            "paper_only": True,
            "positions": positions,
            "marks": marks,
            "mark_source": mark_source,
            "sleeve_equity_usd": eq,
            "cash_usd": cash,
            "generated_at_utc": str(ts),
            "job_mode": mode,
        }

        # v11 sleeves are ETF/bench — use bench_slippage_bps (default 3).
        slip_bps = float(cfg.bench_slippage_bps)
        plan["slippage_bps"] = slip_bps
        plan["fee_model"] = "futu_us_equity+slippage"

        preview = FutuBrokerAdapter(dry_run=True, simulate=True, initial_cash=eq)
        preview._local_cash = float(cash)  # noqa: SLF001
        preview._local_positions = dict(positions)  # noqa: SLF001
        try:
            fills = TargetWeightExecutor(preview, min_trade_notional=25.0).rebalance(
                target, marks, ts, equity=eq
            )
            plan["preview_orders"] = _annotate_fill_costs(
                [
                    {
                        "order_id": f.order_id,
                        "symbol": f.symbol,
                        "side": f.side.value if hasattr(f.side, "value") else str(f.side),
                        "quantity": f.quantity,
                        "price": f.price,
                        "fee": f.fee,
                    }
                    for f in fills
                ],
                slippage_bps=slip_bps,
            )
            # Dry-run local cash: also deduct research costs (broker+slip), like backtest.
            for row in plan["preview_orders"]:
                cost = float(row.get("research_cost_usd") or 0.0)
                side = str(row.get("side") or "").lower()
                if side == "buy":
                    preview._local_cash -= cost  # noqa: SLF001
                elif side == "sell":
                    preview._local_cash -= cost  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            plan["preview_orders"] = []
            plan["preview_error"] = str(exc)

        (base / f"signal_{asof}.json").write_text(json.dumps(plan, indent=2, default=float) + "\n")
        (base / "latest_signal.json").write_text(json.dumps(plan, indent=2, default=float) + "\n")
        log(f"preview_orders={len(plan.get('preview_orders') or [])} slip_bps={slip_bps}")
        for o in plan.get("preview_orders") or []:
            log(
                f"  {o['side']} {o['quantity']:g} {o['symbol']} @~{o['price']} "
                f"fee≈{float(o.get('fee') or 0):.4f} "
                f"(broker≈{float(o.get('broker_fee_usd') or 0):.4f}+"
                f"slip≈{float(o.get('slippage_usd') or 0):.4f})"
            )

        if mode == "signal" or not submit:
            if not submit:
                log("SUBMIT=0 — plan only. Set QRESEARCH_SG_PAPER_SUBMIT=1 for Futu paper.")
            write_paper_state(
                state_path,
                asof=str(asof),
                submitted=False,
                ts=ts,
                preset="v11",
            )
            return 0


        # Guard: empty position query + fat equity usually means OpenD glitched.
        # Without this we re-issue the full target buys (duplicate buy signal).
        if not positions and eq > 0 and cash >= 0:
            invested_hint = float(eq) - float(cash)
            if invested_hint > max(500.0, 0.05 * float(eq)):
                log(
                    f"REFUSE submit: positions empty but equity={eq:.2f} cash={cash:.2f} "
                    f"(invested_hint={invested_hint:.2f}) — likely position_list_query miss; retry later"
                )
                return 3

        if already_ran_today(state_path, str(asof)) and not force:
            log(f"already submitted asof={asof}; QRESEARCH_FORCE=1 to override")
            return 0

        if not has_futu_opend():
            log("REFUSE submit: OpenD not reachable")
            return 3

        live = FutuBrokerAdapter.from_opend(dry_run=False, simulate=True, default_market="US")
        submit_error: str | None = None
        try:
            try:
                fills = TargetWeightExecutor(live, min_trade_notional=25.0).rebalance(
                    target, marks, ts, equity=eq
                )
            except Exception as exc:  # noqa: BLE001
                # Keep any legs that already filled (e.g. QQQ before SPY timed out).
                fills = list(live.fills())
                submit_error = str(exc)
                log(f"WARN: rebalance interrupted after {len(fills)} fill(s): {exc}")

            fill_rows = _annotate_fill_costs(
                [
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
                ],
                slippage_bps=slip_bps,
            )
            for row in fill_rows:
                log(
                    f"  cost {row['side']} {row['quantity']:g} {row['symbol']}: "
                    f"broker≈{row['broker_fee_usd']:.4f} slip≈{row['slippage_usd']:.4f} "
                    f"total≈{row['research_cost_usd']:.4f} (SIMULATE cash may omit synthetic slip)"
                )
            positions_after = live.get_positions()
            cash_after = live.get_cash()
            result = {
                **plan,
                "fills": fill_rows,
                "positions_after": positions_after,
                "cash_after": cash_after,
            }
            log_path = base / "logs" / f"run_{ts.strftime('%Y%m%dT%H%M%S')}.json"
            log_path.write_text(json.dumps(result, indent=2, default=float) + "\n")
            (base / "latest_run.json").write_text(json.dumps(result, indent=2, default=float) + "\n")
            append_fills_ledger(
                base,
                fill_rows,
                meta={"asof": str(asof), "run_at": str(ts), "broker": "futu", "preset": "v11"},
            )
            audit = reconcile_fills(
                preview_orders=plan.get("preview_orders") or [],
                fills=fill_rows,
                positions_before=positions,
                positions_after=positions_after,
                asof=str(asof),
                run_at=str(ts),
            )
            write_audit(base, audit)
            write_paper_state(
                state_path,
                asof=str(asof),
                # Partial failure must stay retryable (e.g. QQQ filled, SPY timed out).
                submitted=not bool(submit_error),
                ts=ts,
                preset="v11",
                extra={
                    "paper_only": True,
                    "broker": "futu",
                    "n_fills": len(fills),
                    "fill_audit": audit.get("status"),
                    "partial": bool(submit_error),
                    **({"submit_error": submit_error} if submit_error else {}),
                },
            )
            if submit_error:
                result["submit_error"] = submit_error
                (base / "latest_run.json").write_text(json.dumps(result, indent=2, default=float) + "\n")
            log(f"futu paper fills={len(fills)} → {log_path}")
            log(f"fill_audit={audit.get('status')} issues={audit.get('n_issues')}")
            for line in audit.get("lines") or []:
                log(
                    f"  [{line.get('status')}] {line.get('side')} "
                    f"preview={line.get('preview_qty')} fill={line.get('fill_qty')} "
                    f"{line.get('symbol')} @ {line.get('fill_price')}"
                )
            for issue in audit.get("issues") or []:
                log(f"  !! {issue}")
            if submit_error:
                log(f"REFUSE complete: partial submit — {submit_error}")
                return 4
        finally:
            live.close()
        return 0
    finally:
        broker.close()


if __name__ == "__main__":
    raise SystemExit(main())
