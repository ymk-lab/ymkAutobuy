"""Sleeve daily blotter: equity, day PnL, realized slip vs mark."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LEDGER = "sleeve_daily.jsonl"
LATEST = "latest_sleeve_day.json"


def _f(x: object, default: float = 0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def realized_slip(
    *,
    side: str,
    fill_price: float,
    mark_price: float,
    quantity: float,
) -> dict[str, float | None]:
    """Slip vs an official mark (09:40 or snapshot).

    Buy above mark or sell below mark is a positive cost in USD/bps.
    """
    fill = _f(fill_price)
    mark = _f(mark_price)
    qty = abs(_f(quantity))
    if fill <= 0 or mark <= 0 or qty <= 0:
        return {"mark_price": mark or None, "realized_slip_bps": None, "realized_slip_usd": None}
    raw_bps = (fill - mark) / mark * 10_000.0
    signed = raw_bps if str(side).lower() == "buy" else -raw_bps
    usd = qty * mark * (signed / 10_000.0)
    return {
        "mark_price": mark,
        "realized_slip_bps": signed,
        "realized_slip_usd": usd,
    }


def annotate_marks(rows: list[dict[str, Any]], marks: dict[str, float] | None) -> list[dict[str, Any]]:
    marks = {str(k).upper(): _f(v) for k, v in (marks or {}).items()}
    out: list[dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        sym = str(r.get("symbol") or "").upper()
        extra = realized_slip(
            side=str(r.get("side") or ""),
            fill_price=_f(r.get("price")),
            mark_price=marks.get(sym, 0.0),
            quantity=_f(r.get("quantity") if r.get("quantity") is not None else r.get("qty")),
        )
        r.update(extra)
        out.append(r)
    return out


def _weighted_bps(rows: list[dict[str, Any]], bps_key: str) -> float | None:
    num = 0.0
    den = 0.0
    for r in rows:
        bps = r.get(bps_key)
        notion = abs(_f(r.get("notional"), _f(r.get("quantity")) * _f(r.get("price"))))
        if bps is None or notion <= 0:
            continue
        num += float(bps) * notion
        den += notion
    if den <= 0:
        return None
    return num / den


def load_sleeve_daily(base: Path, *, limit: int = 90) -> list[dict[str, Any]]:
    path = Path(base) / LEDGER
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return rows[-max(1, limit) :]


def _prev_equity(rows: list[dict[str, Any]], asof: str) -> float | None:
    prior = [r for r in rows if str(r.get("asof") or "") < str(asof) and r.get("equity") is not None]
    if not prior:
        return None
    return _f(prior[-1].get("equity"))


def upsert_sleeve_day(base: Path, row: dict[str, Any]) -> dict[str, Any]:
    """One row per asof; later once overwrites an earlier signal snapshot."""
    out = Path(base)
    out.mkdir(parents=True, exist_ok=True)
    asof = str(row.get("asof") or "")
    existing = load_sleeve_daily(out, limit=10_000)
    prev_eq = _prev_equity(existing, asof)
    equity = _f(row.get("equity"))
    day_pnl = None if prev_eq is None else equity - prev_eq
    day_pnl_pct = None if prev_eq in (None, 0) else (equity - prev_eq) / prev_eq
    payload = {
        **row,
        "equity": equity,
        "prev_equity": prev_eq,
        "day_pnl": day_pnl,
        "day_pnl_pct": day_pnl_pct,
        "written_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    kept = [r for r in existing if str(r.get("asof") or "") != asof]
    kept.append(payload)
    kept.sort(key=lambda r: str(r.get("asof") or ""))
    path = out / LEDGER
    path.write_text(
        "".join(json.dumps(r, default=float) + "\n" for r in kept),
        encoding="utf-8",
    )
    (out / LATEST).write_text(json.dumps(payload, indent=2, default=float) + "\n", encoding="utf-8")
    return payload


def record_sleeve_day(
    base: Path,
    *,
    asof: str,
    job: str,
    env: str,
    sleeve_notional: float,
    cash: float,
    equity: float,
    positions: dict[str, float] | None,
    marks: dict[str, float] | None,
    fills: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    pos = {str(k).upper(): _f(v) for k, v in (positions or {}).items()}
    mk = {str(k).upper(): _f(v) for k, v in (marks or {}).items()}
    mv = 0.0
    for sym, qty in pos.items():
        px = mk.get(sym)
        if px and px > 0:
            mv += qty * px
    filled = annotate_marks(list(fills or []), mk)
    notion = sum(abs(_f(r.get("quantity")) * _f(r.get("price"))) for r in filled)
    fee = sum(_f(r.get("fee") or r.get("research_cost_usd")) for r in filled)
    slip_usd = sum(_f(r.get("realized_slip_usd")) for r in filled if r.get("realized_slip_usd") is not None)
    return upsert_sleeve_day(
        base,
        {
            "asof": asof,
            "job": job,
            "env": env,
            "sleeve_notional": float(sleeve_notional),
            "cash": float(cash),
            "equity": float(equity),
            "positions_mv": mv,
            "n_positions": len([q for q in pos.values() if abs(q) > 1e-12]),
            "n_fills": len(filled),
            "fills_notional": notion,
            "model_fee_usd": fee,
            "realized_slip_usd": slip_usd if filled else 0.0,
            "realized_slip_bps": _weighted_bps(filled, "realized_slip_bps"),
            "positions": pos,
        },
    )
