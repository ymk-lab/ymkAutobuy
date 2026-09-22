"""Locked Plan: written by Signal, consumed by Once."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PLAN_NAME = "locked_plan.json"
LATEST_SIGNAL = "latest_signal.json"


def plan_path(out_dir: Path) -> Path:
    return Path(out_dir) / PLAN_NAME


def load_locked_plan(out_dir: Path) -> dict[str, Any] | None:
    path = plan_path(out_dir)
    if not path.is_file():
        fallback = Path(out_dir) / LATEST_SIGNAL
        if not fallback.is_file():
            return None
        path = fallback
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def write_locked_plan(out_dir: Path, plan: dict[str, Any]) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = dict(plan)
    payload["locked"] = True
    text = json.dumps(payload, indent=2, default=float) + "\n"
    dest = plan_path(out)
    dest.write_text(text, encoding="utf-8")
    (out / LATEST_SIGNAL).write_text(text, encoding="utf-8")
    asof = payload.get("asof")
    if asof:
        (out / f"signal_{asof}.json").write_text(text, encoding="utf-8")
    return dest


def slip_bps(plan_price: float, fill_price: float) -> float | None:
    px = float(plan_price or 0.0)
    fill = float(fill_price or 0.0)
    if px <= 0 or fill <= 0:
        return None
    return abs(fill - px) / px * 10_000.0
