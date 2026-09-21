"""Unit tests for Structure Gate v14 stabilize (immediate enter + min hold)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from qresearch.strategy.structure_gate import StructureGateConfig, stabilize_modes_v13


def _series(vals, name="x"):
    idx = pd.bdate_range("2025-01-01", periods=len(vals))
    return pd.Series(vals, index=idx, name=name)


def test_v14_enter_immediate_without_trail_gate():
    cfg = StructureGateConfig.v14()
    # trail below v13 enter threshold (+3.5%) but unlocked raw wants ers
    raw = _series(["bench", "ers", "ers", "ers", "ers"])
    trail = _series([0.0, 0.01, 0.01, 0.01, 0.01])  # only +1%
    harsh = _series([False] * 5)
    mode, _ = stabilize_modes_v13(raw, trail, harsh, harsh, config=cfg)
    assert list(mode) == ["bench", "ers", "ers", "ers", "ers"]


def test_v13_still_blocks_weak_enter():
    cfg = StructureGateConfig.v13()
    raw = _series(["bench", "ers", "ers", "ers", "ers"])
    trail = _series([0.0, 0.01, 0.01, 0.01, 0.01])
    harsh = _series([False] * 5)
    mode, audit = stabilize_modes_v13(raw, trail, harsh, harsh, config=cfg)
    assert mode.iloc[1] == "bench"
    assert float(audit["mode_switch_blocked"].iloc[1]) == 1.0


def test_v14_min_hold_blocks_soft_exit_for_3_days():
    cfg = StructureGateConfig.v14()
    # enter ers day1; raw wants bench from day2 with exit trail satisfied
    raw = _series(["ers", "bench", "bench", "bench", "bench", "bench"])
    trail = _series([-0.05, -0.05, -0.05, -0.05, -0.05, -0.05])  # <= exit -1.5%
    harsh = _series([False] * 6)
    mode, _ = stabilize_modes_v13(raw, trail, harsh, harsh, config=cfg)
    # days_in_stock: day0=1, day1=2, day2=3 → soft exit allowed when days_in_stock>=3
    # On day index 0 seeded ers (days=1). day1 want bench blocked (hold 2). day2 blocked (hold 3).
    # day3: days_in_stock would be 4 before switch check... after day2 still ers with days=3,
    # day3: days_in_stock starts at 3, need < min_hold to block → 3 < 3 is False → allow exit.
    assert list(mode.iloc[:3]) == ["ers", "ers", "ers"]
    assert mode.iloc[3] == "bench"


def test_v14_harsh_cash_pierces_min_hold():
    cfg = StructureGateConfig.v14()
    raw = _series(["ers", "cash", "cash"])
    trail = _series([0.05, 0.05, 0.05])
    harsh = _series([False, True, True])
    mode, audit = stabilize_modes_v13(raw, trail, harsh, harsh, config=cfg)
    assert mode.iloc[1] == "cash"
    assert float(audit["risk_override_pierce"].iloc[1]) == 1.0
