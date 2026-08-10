#!/usr/bin/env python3
"""One-shot probe: RTH 09:40 (1m) vs daily open.

Not used by the live paper cron. For testing how far 09:40 execution
diverges from next-open backtest assumptions.

Prefer Futu OpenD ``KLType.K_1M`` when reachable; otherwise Yahoo 1m
(last ~7 trading days only).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

ET = ZoneInfo("America/New_York")
OUT_DEFAULT = ROOT / "examples" / "data" / "structure_gate_v11_paper" / "probe_rth_0940.json"


def _parse_symbols(s: str) -> list[str]:
    return [x.strip().upper() for x in s.split(",") if x.strip()]


def _day_range(days: int, end: date | None = None) -> tuple[date, date]:
    end = end or date.today()
    # calendar pad so we cover ~N sessions
    start = end - timedelta(days=max(days * 2 + 4, 10))
    return start, end


def fetch_1m_futu(symbols: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
    from futu import AuType, KLType, OpenQuoteContext, RET_OK

    from qresearch.brokers.futu import has_futu_opend, load_dotenv_if_present
    from qresearch.brokers.futu.config import futu_opend_host, futu_opend_port
    from qresearch.brokers.futu.symbols import to_futu_code

    load_dotenv_if_present()
    if not has_futu_opend():
        raise RuntimeError("OpenD not reachable")

    host, port = futu_opend_host(), futu_opend_port()
    ctx = OpenQuoteContext(host=host, port=port)
    out: dict[str, pd.DataFrame] = {}
    try:
        for sym in symbols:
            code = to_futu_code(sym)
            frames: list[pd.DataFrame] = []
            page_key = None
            while True:
                ret, data, page_key = ctx.request_history_kline(
                    code,
                    start=str(start),
                    end=str(end),
                    ktype=KLType.K_1M,
                    autype=AuType.NONE,
                    max_count=1000,
                    page_req_key=page_key,
                )
                if ret != RET_OK:
                    raise RuntimeError(f"futu {code}: {data}")
                if data is None or len(data) == 0:
                    break
                frames.append(data)
                if page_key is None:
                    break
            if not frames:
                continue
            raw = pd.concat(frames, ignore_index=True)
            ts = pd.to_datetime(raw["time_key"])
            # Futu US bars are typically Eastern wall-clock without tz
            if getattr(ts.dt, "tz", None) is None:
                ts = ts.dt.tz_localize(ET)
            else:
                ts = ts.dt.tz_convert(ET)
            df = pd.DataFrame(
                {
                    "open": raw["open"].astype(float).to_numpy(),
                    "high": raw["high"].astype(float).to_numpy(),
                    "low": raw["low"].astype(float).to_numpy(),
                    "close": raw["close"].astype(float).to_numpy(),
                    "volume": raw["volume"].astype(float).to_numpy(),
                },
                index=pd.DatetimeIndex(ts),
            )
            out[sym] = df[~df.index.duplicated(keep="last")].sort_index()
    finally:
        ctx.close()
    return out


def fetch_1m_yahoo(symbols: list[str], days: int) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    # Yahoo allows at most ~7–8 calendar days of 1m per request.
    period = f"{min(max(int(days) + 2, 5), 7)}d"
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        raw = yf.Ticker(sym).history(period=period, interval="1m", auto_adjust=False)
        if raw is None or raw.empty:
            continue
        idx = raw.index
        if idx.tz is None:
            idx = idx.tz_localize(ET)
        else:
            idx = idx.tz_convert(ET)
        df = pd.DataFrame(
            {
                "open": raw["Open"].astype(float).to_numpy(),
                "high": raw["High"].astype(float).to_numpy(),
                "low": raw["Low"].astype(float).to_numpy(),
                "close": raw["Close"].astype(float).to_numpy(),
                "volume": raw["Volume"].astype(float).to_numpy(),
            },
            index=pd.DatetimeIndex(idx),
        )
        out[sym] = df[~df.index.duplicated(keep="last")].sort_index()
    return out


def fetch_daily_open(symbols: list[str], start: date, end: date) -> dict[str, dict[str, float]]:
    """symbol -> {YYYY-MM-DD: daily_open}."""
    # Prefer local paper cache when present
    cache = ROOT / "examples" / "data" / "structure_gate_v11_paper" / "cache_ohlcv"
    out: dict[str, dict[str, float]] = {}
    for sym in symbols:
        path = cache / f"{sym}.csv"
        if path.exists():
            df = pd.read_csv(path, parse_dates=["datetime"]).set_index("datetime")
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            m: dict[str, float] = {}
            for ts, row in df.iterrows():
                d = ts.date() if hasattr(ts, "date") else pd.Timestamp(ts).date()
                if start <= d <= end:
                    m[str(d)] = float(row["open"])
            out[sym] = m
            continue
        import yfinance as yf

        raw = yf.Ticker(sym).history(
            start=str(start), end=str(end + timedelta(days=1)), interval="1d", auto_adjust=False
        )
        m = {}
        for ts, row in raw.iterrows():
            d = ts.tz_convert(ET).date() if ts.tzinfo else ts.date()
            m[str(d)] = float(row["Open"])
        out[sym] = m
    return out


def summarize(
    bars: dict[str, pd.DataFrame],
    daily_opens: dict[str, dict[str, float]],
    *,
    source: str,
    max_days: int,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for sym, df in bars.items():
        days = sorted({ts.date() for ts in df.index})[-max_days:]
        for d in days:
            t930 = pd.Timestamp(datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET))
            t940 = pd.Timestamp(datetime(d.year, d.month, d.day, 9, 40, tzinfo=ET))
            dopen = daily_opens.get(sym, {}).get(str(d))
            r930 = df.loc[t930] if t930 in df.index else None
            r940 = df.loc[t940] if t940 in df.index else None
            if r940 is None:
                continue
            o940 = float(r940["open"])
            c940 = float(r940["close"])
            o930 = float(r930["open"]) if r930 is not None else None
            rec: dict[str, Any] = {
                "symbol": sym,
                "date": str(d),
                "daily_open": dopen,
                "open_0930": o930,
                "open_0940": o940,
                "close_0940": c940,
            }
            if dopen and dopen > 0:
                rec["bps_0940_open_vs_daily"] = round((o940 / dopen - 1.0) * 10000.0, 2)
                rec["bps_0940_close_vs_daily"] = round((c940 / dopen - 1.0) * 10000.0, 2)
                if o930:
                    rec["bps_0930_open_vs_daily"] = round((o930 / dopen - 1.0) * 10000.0, 2)
            rows.append(rec)

    by_sym: dict[str, list[float]] = {}
    for r in rows:
        if "bps_0940_open_vs_daily" in r:
            by_sym.setdefault(r["symbol"], []).append(float(r["bps_0940_open_vs_daily"]))
    summary = {
        sym: {
            "n": len(v),
            "mean_bps_0940_open_vs_daily": round(sum(v) / len(v), 2),
            "abs_mean_bps": round(sum(abs(x) for x in v) / len(v), 2),
            "min_bps": round(min(v), 2),
            "max_bps": round(max(v), 2),
        }
        for sym, v in by_sym.items()
        if v
    }
    return {
        "ok": True,
        "source": source,
        "note": "test-only; not wired into paper cron",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "summary": summary,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default="QQQ,SPY,SMH")
    ap.add_argument("--days", type=int, default=5, help="recent sessions to report")
    ap.add_argument("--source", choices=("auto", "futu", "yahoo"), default="auto")
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args()

    symbols = _parse_symbols(args.symbols)
    start, end = _day_range(args.days)

    source = args.source
    bars: dict[str, pd.DataFrame] = {}
    err: str | None = None
    if source in ("auto", "futu"):
        try:
            bars = fetch_1m_futu(symbols, start, end)
            source = "futu"
        except Exception as e:  # noqa: BLE001 — probe should keep going
            err = f"futu: {e}"
            if args.source == "futu":
                print(err, file=sys.stderr)
                return 2
    if not bars and source in ("auto", "yahoo"):
        bars = fetch_1m_yahoo(symbols, args.days)
        source = "yahoo"

    if not bars:
        print(err or "no bars", file=sys.stderr)
        return 1

    # align daily open window to actual 1m coverage
    all_dates = sorted({ts.date() for df in bars.values() for ts in df.index})
    d0, d1 = all_dates[0], all_dates[-1]
    daily = fetch_daily_open(symbols, d0, d1)
    report = summarize(bars, daily, source=source, max_days=args.days)
    if err:
        report["futu_error"] = err

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"source={report['source']} rows={len(report['rows'])} → {args.out}")
    for sym, s in report["summary"].items():
        print(
            f"  {sym}: n={s['n']} mean={s['mean_bps_0940_open_vs_daily']:+.1f}bps "
            f"abs_mean={s['abs_mean_bps']:.1f}bps "
            f"range=[{s['min_bps']:+.1f},{s['max_bps']:+.1f}]"
        )
    # last session detail
    last_day = max((r["date"] for r in report["rows"]), default=None)
    if last_day:
        print(f"last session {last_day}:")
        for r in report["rows"]:
            if r["date"] != last_day:
                continue
            print(
                f"  {r['symbol']} daily_open={r.get('daily_open')} "
                f"09:40_open={r['open_0940']} "
                f"Δ={r.get('bps_0940_open_vs_daily')}bps"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
