"""Regression: recheck must not treat historical ledger as today's fills."""

from __future__ import annotations

import json
from pathlib import Path

from qresearch.paper.fill_audit import append_fills_ledger, audit_from_out_dir, write_audit


def test_audit_ignores_ledger_when_latest_run_has_empty_fills(tmp_path: Path) -> None:
    base = tmp_path / "paper"
    base.mkdir()
    (base / "latest_signal.json").write_text(
        json.dumps(
            {
                "asof": "2026-08-10",
                "preview_orders": [],
                "positions": {"SPY.US": 25.0, "QQQ.US": 20.0},
                "target": {"SPY.US": 0.4, "QQQ.US": 0.3},
            }
        )
        + "\n"
    )
    (base / "latest_run.json").write_text(
        json.dumps(
            {
                "asof": "2026-08-10",
                "preview_orders": [],
                "fills": [],
                "positions": {"SPY.US": 25.0, "QQQ.US": 20.0},
                "positions_after": {"SPY.US": 25.0, "QQQ.US": 20.0},
                "generated_at_utc": "2026-08-11 09:40:02",
            }
        )
        + "\n"
    )
    (base / "state.json").write_text(
        json.dumps({"asof": "2026-08-10", "submitted": True, "n_fills": 0}) + "\n"
    )
    (base / "account_live.json").write_text(
        json.dumps({"positions": {"SPY.US": 25.0, "QQQ.US": 20.0}}) + "\n"
    )
    # Historical establishing buys — must not poison recheck.
    append_fills_ledger(
        base,
        [
            {"symbol": "QQQ.US", "side": "buy", "quantity": 20, "price": 720, "order_id": "1"},
            {"symbol": "SPY.US", "side": "buy", "quantity": 25, "price": 770, "order_id": "2"},
            {"symbol": "QQQ.US", "side": "buy", "quantity": 20, "price": 721, "order_id": "3"},
            {"symbol": "SPY.US", "side": "buy", "quantity": 25, "price": 771, "order_id": "4"},
        ],
        meta={"asof": "2026-08-07"},
    )

    audit = audit_from_out_dir(base)
    write_audit(base, audit)
    assert audit["status"] == "pass"
    assert audit["n_fills"] == 0
    assert audit["n_preview"] == 0
    assert audit["ok"] is True
