"""Freeze / Submit / Trading Environment persisted next to paper output."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OPS_FILE = "ops_state.json"
SLIP_BPS_LIMIT = 50.0
CONFIRM_PHRASE = "CONFIRM"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class OpsState:
    frozen: bool = False
    freeze_reason: str = ""
    frozen_at: str = ""
    submit_enabled: bool = False
    trading_env: str = "SIMULATE"
    buying_power_cap: bool = False
    notional_cap: float = 50_000.0
    flatten_requested: bool = False
    flatten_all: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "OpsState":
        raw = raw or {}
        env = str(raw.get("trading_env") or "SIMULATE").upper()
        if env not in {"SIMULATE", "REAL"}:
            env = "SIMULATE"
        try:
            cap = float(raw.get("notional_cap") or 50_000.0)
        except (TypeError, ValueError):
            cap = 50_000.0
        return cls(
            frozen=bool(raw.get("frozen")),
            freeze_reason=str(raw.get("freeze_reason") or ""),
            frozen_at=str(raw.get("frozen_at") or ""),
            submit_enabled=bool(raw.get("submit_enabled")),
            trading_env=env,
            buying_power_cap=bool(raw.get("buying_power_cap")),
            notional_cap=cap,
            flatten_requested=bool(raw.get("flatten_requested")),
            flatten_all=bool(raw.get("flatten_all")),
        )


def ops_path(out_dir: Path) -> Path:
    return Path(out_dir) / OPS_FILE


def load_ops(out_dir: Path) -> OpsState:
    path = ops_path(out_dir)
    if not path.is_file():
        return OpsState(
            submit_enabled=_env_bool("QRESEARCH_SG_PAPER_SUBMIT", False),
            trading_env=_env_trd(),
            buying_power_cap=_env_bool("QRESEARCH_BUYING_POWER_CAP", False),
            notional_cap=_env_float("QRESEARCH_SLEEVE_USD", 50_000.0) or 50_000.0,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return OpsState()
    return OpsState.from_dict(raw if isinstance(raw, dict) else {})


def save_ops(out_dir: Path, state: OpsState) -> None:
    path = ops_path(out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")


def freeze(out_dir: Path, reason: str) -> OpsState:
    state = load_ops(out_dir)
    state.frozen = True
    state.freeze_reason = reason
    state.frozen_at = _now()
    save_ops(out_dir, state)
    return state


def unfreeze(out_dir: Path) -> OpsState:
    state = load_ops(out_dir)
    state.frozen = False
    state.freeze_reason = ""
    state.frozen_at = ""
    save_ops(out_dir, state)
    return state


def allow_live_locked() -> bool:
    return _env_bool("QRESEARCH_FUTU_ALLOW_LIVE", False)


def effective_simulate(state: OpsState) -> bool:
    if state.trading_env != "REAL":
        return True
    return not allow_live_locked()


def refuse_once_reason(
    state: OpsState,
    *,
    opend_ok: bool,
    plan_asof: str | None,
    expected_asof: str | None,
) -> str | None:
    if state.frozen:
        return f"frozen: {state.freeze_reason or 'manual'}"
    if not state.submit_enabled:
        return "submit gate closed"
    if not opend_ok:
        return "OpenD down or login dead"
    if state.trading_env == "REAL" and not allow_live_locked():
        return "REAL selected but ALLOW_LIVE is off"
    if not plan_asof:
        return "no Locked Plan"
    if expected_asof and str(plan_asof) != str(expected_asof):
        return f"Signal asof {plan_asof} is not last complete session {expected_asof}"
    return None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float | None = None) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_trd() -> str:
    raw = (os.getenv("FUTU_TRD_ENV") or "SIMULATE").strip().upper()
    return raw if raw in {"SIMULATE", "REAL"} else "SIMULATE"
