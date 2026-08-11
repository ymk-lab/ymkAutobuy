"""Fill-by-fill audit: preview vs actual fills vs positions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sym(x: object) -> str:
    return str(x or "").strip().upper()


def _side(x: object) -> str:
    s = str(x or "").strip().lower()
    if s in {"buy", "b", "1"}:
        return "buy"
    if s in {"sell", "s", "2"}:
        return "sell"
    return s


def _f(x: object, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def _row_key(symbol: str, side: str) -> str:
    return f"{_sym(symbol)}|{_side(side)}"


def normalize_fill_row(row: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    symbol = _sym(row.get("symbol"))
    side = _side(row.get("side"))
    qty = _f(row.get("quantity") if row.get("quantity") is not None else row.get("qty"))
    price = _f(row.get("price") if row.get("price") is not None else row.get("dealt_avg_price"))
    fee = _f(row.get("fee"))
    return {
        "order_id": str(row.get("order_id") or ""),
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "price": price,
        "fee": fee,
        "notional": qty * price,
        "timestamp": str(row.get("timestamp") or row.get("at") or ""),
        "source": source or str(row.get("source") or ""),
    }


def signed_qty_delta(fills: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for f in fills:
        sym = _sym(f.get("symbol"))
        if not sym:
            continue
        q = _f(f.get("quantity"))
        if _side(f.get("side")) == "sell":
            q = -q
        out[sym] = out.get(sym, 0.0) + q
    return out


def reconcile_fills(
    *,
    preview_orders: list[dict[str, Any]] | None,
    fills: list[dict[str, Any]] | None,
    positions_before: dict[str, Any] | None = None,
    positions_after: dict[str, Any] | None = None,
    asof: str | None = None,
    run_at: str | None = None,
    tolerance_qty: float = 1e-6,
    tolerance_px_bps: float = 50.0,
) -> dict[str, Any]:
    """Compare planned preview orders to actual fills and position deltas."""
    preview = [normalize_fill_row(r, source="preview") for r in (preview_orders or [])]
    actual = [normalize_fill_row(r, source="fill") for r in (fills or [])]

    preview_map: dict[str, dict[str, Any]] = {}
    for r in preview:
        preview_map[_row_key(r["symbol"], r["side"])] = r

    fill_map: dict[str, dict[str, Any]] = {}
    for r in actual:
        k = _row_key(r["symbol"], r["side"])
        if k in fill_map:
            prev = fill_map[k]
            qty = prev["quantity"] + r["quantity"]
            notional = prev["notional"] + r["notional"]
            fee = prev["fee"] + r["fee"]
            fill_map[k] = {
                **prev,
                "quantity": qty,
                "notional": notional,
                "fee": fee,
                "price": (notional / qty) if qty else prev["price"],
                "order_id": f"{prev['order_id']},{r['order_id']}".strip(","),
            }
        else:
            fill_map[k] = r

    keys = sorted(set(preview_map) | set(fill_map))
    lines: list[dict[str, Any]] = []
    issues: list[str] = []

    for k in keys:
        p = preview_map.get(k)
        a = fill_map.get(k)
        symbol, side = k.split("|", 1)
        pq = _f(p.get("quantity")) if p else 0.0
        aq = _f(a.get("quantity")) if a else 0.0
        pp = _f(p.get("price")) if p else None
        ap = _f(a.get("price")) if a else None
        qty_ok = abs(pq - aq) <= tolerance_qty
        px_ok = True
        px_bps = None
        if pp and ap and pp > 0:
            px_bps = abs(ap - pp) / pp * 1e4
            px_ok = px_bps <= tolerance_px_bps
        status = "ok"
        if p is None:
            status = "extra_fill"
            issues.append(f"extra fill {side} {aq:g} {symbol}")
        elif a is None:
            status = "missing_fill"
            issues.append(f"missing fill {side} {pq:g} {symbol}")
        elif not qty_ok:
            status = "qty_mismatch"
            issues.append(f"qty mismatch {symbol}: preview {pq:g} vs fill {aq:g}")
        elif not px_ok:
            status = "price_warn"
            issues.append(f"price drift {symbol}: {px_bps:.1f} bps")

        lines.append(
            {
                "symbol": symbol,
                "side": side,
                "preview_qty": pq if p else None,
                "fill_qty": aq if a else None,
                "preview_price": pp,
                "fill_price": ap,
                "price_bps": px_bps,
                "fee": _f(a.get("fee")) if a else 0.0,
                "notional": _f(a.get("notional")) if a else (_f(p.get("notional")) if p else 0.0),
                "order_id": (a or p or {}).get("order_id") or "",
                "status": status,
                "qty_ok": qty_ok if p and a else False,
                "price_ok": px_ok if p and a else False,
            }
        )

    before = {_sym(k): _f(v) for k, v in (positions_before or {}).items() if _sym(k)}
    after = {_sym(k): _f(v) for k, v in (positions_after or {}).items() if _sym(k)}
    expected_after = dict(before)
    for sym, dq in signed_qty_delta(actual).items():
        expected_after[sym] = expected_after.get(sym, 0.0) + dq

    pos_lines: list[dict[str, Any]] = []
    pos_ok = True
    if after or before or actual:
        symbols = sorted(set(before) | set(after) | set(expected_after))
        for sym in symbols:
            b = before.get(sym, 0.0)
            e = expected_after.get(sym, 0.0)
            a = after.get(sym, 0.0) if after else None
            ok = a is None or abs(e - a) <= tolerance_qty
            if a is not None and not ok:
                pos_ok = False
                issues.append(f"position {sym}: expected {e:g} after fills, account has {a:g}")
            pos_lines.append(
                {
                    "symbol": sym,
                    "before": b,
                    "expected_after": e,
                    "after": a,
                    "ok": ok if a is not None else None,
                }
            )

    hard_fail = any(
        x["status"] in {"missing_fill", "extra_fill", "qty_mismatch"} for x in lines
    ) or (not pos_ok and bool(after))
    warn = any(x["status"] == "price_warn" for x in lines)
    pending = bool(preview) and not actual

    if pending and not after:
        # Plan-only: preview exists but nothing submitted yet.
        status = "pending"
        ok = True
        issues = [f"pending fill {x['side']} {x.get('preview_qty')} {x['symbol']}" for x in lines]
        hard_fail = False
    else:
        status = "fail" if hard_fail else ("warn" if warn else "pass")
        ok = not hard_fail

    return {
        "ok": ok,
        "status": status,
        "asof": asof,
        "run_at": run_at,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_preview": len(preview),
        "n_fills": len(actual),
        "n_issues": len(issues),
        "issues": issues,
        "lines": lines,
        "positions": pos_lines,
        "fills": actual,
        "preview_orders": preview,
    }


def append_fills_ledger(base: Path, rows: list[dict[str, Any]], *, meta: dict[str, Any] | None = None) -> Path:
    path = base / "fills_ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            payload = {**normalize_fill_row(r), **(meta or {}), "ledger_at_utc": stamp}
            fh.write(json.dumps(payload, default=float) + "\n")
    return path


def load_fills_ledger(base: Path, *, limit: int = 200) -> list[dict[str, Any]]:
    path = base / "fills_ledger.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[dict[str, Any]] = []
    for ln in lines[-max(1, limit) :]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def audit_from_out_dir(base: Path) -> dict[str, Any]:
    """Build audit from paper out dir artifacts."""
    def _read(name: str) -> dict[str, Any]:
        p = base / name
        if not p.is_file():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    signal = _read("latest_signal.json")
    run = _read("latest_run.json")
    account = _read("account_live.json")
    state = _read("state.json")

    preview = run.get("preview_orders") or signal.get("preview_orders") or []
    # Prefer latest_run fills even when empty (means this run placed 0 orders).
    # Only fall back to the historical ledger when latest_run.json is missing —
    # otherwise "recheck" aggregates old buys against today's empty preview
    # and falsely reports extra_fill / position mismatch.
    run_path = base / "latest_run.json"
    if run_path.is_file():
        fills = list(run.get("fills") or [])
    else:
        fills = load_fills_ledger(base, limit=50)
        asof_hint = str(signal.get("asof") or state.get("asof") or "")
        if asof_hint:
            fills = [r for r in fills if str(r.get("asof") or "") == asof_hint]

    positions_before = run.get("positions") or signal.get("positions") or {}
    positions_after = run.get("positions_after")
    if positions_after is None and account.get("positions") is not None:
        positions_after = account.get("positions") or {}

    audit = reconcile_fills(
        preview_orders=preview,
        fills=fills,
        positions_before=positions_before,
        positions_after=positions_after,
        asof=str(run.get("asof") or signal.get("asof") or state.get("asof") or ""),
        run_at=str(run.get("generated_at_utc") or state.get("at") or ""),
    )
    # If account already shows the expected post-fill positions but latest_run
    # is missing (e.g. copied signal only), mark as needs_run_file rather than pass.
    if audit.get("status") == "pending" and bool(state.get("submitted")) and not run.get("fills"):
        audit["ok"] = False
        audit["status"] = "fail"
        audit["issues"] = list(audit.get("issues") or []) + [
            "state.submitted=true but latest_run.json fills missing — copy run log from paper host"
        ]
        audit["n_issues"] = len(audit["issues"])
    audit["sources"] = {
        "signal": bool(signal),
        "latest_run": bool(run),
        "account_live": bool(account),
        "has_fills": bool(fills),
        "submitted": bool(state.get("submitted")),
    }
    return audit


def write_audit(base: Path, audit: dict[str, Any]) -> Path:
    path = base / "latest_fill_audit.json"
    path.write_text(json.dumps(audit, indent=2, default=float) + "\n", encoding="utf-8")
    return path
