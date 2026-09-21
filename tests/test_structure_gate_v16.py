"""Unit tests for Structure Gate v16 (dual trail 20/70)."""

from __future__ import annotations

from qresearch.strategy.structure_gate import StructureGateConfig


def test_v16_long_windows_are_70():
    cfg = StructureGateConfig.v16()
    assert cfg.leadership_trail_days == 20
    assert cfg.sticky_trail_days == 70
    assert cfg.strong_lookback == 70
    assert cfg.ers_lag_lookback == 70


def test_v16_keeps_v13_mode_locks():
    v13 = StructureGateConfig.v13()
    v16 = StructureGateConfig.v16()
    assert v16.mode_hysteresis_enabled is True
    assert v16.mode_enter_immediate is False
    assert v16.mode_min_hold_days == 0
    assert v16.mode_enter_trail == v13.mode_enter_trail
    assert v16.mode_exit_trail == v13.mode_exit_trail
    assert v16.mode_switch_cooldown_days == v13.mode_switch_cooldown_days
    assert v16.risk_override_enabled is True
    assert v16.mild_defense_dd == v13.mild_defense_dd
    assert v16.harsh_defense_dd == v13.harsh_defense_dd
