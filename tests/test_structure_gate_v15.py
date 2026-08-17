"""Unit tests for Structure Gate v15 (dual trail 20/50)."""

from __future__ import annotations

from qresearch.strategy.structure_gate import StructureGateConfig


def test_v15_long_windows_are_50():
    cfg = StructureGateConfig.v15()
    assert cfg.leadership_trail_days == 20
    assert cfg.sticky_trail_days == 50
    assert cfg.strong_lookback == 50
    assert cfg.ers_lag_lookback == 50


def test_v15_keeps_v13_mode_locks():
    v13 = StructureGateConfig.v13()
    v15 = StructureGateConfig.v15()
    assert v15.mode_hysteresis_enabled is True
    assert v15.mode_enter_immediate is False
    assert v15.mode_min_hold_days == 0
    assert v15.mode_enter_trail == v13.mode_enter_trail
    assert v15.mode_exit_trail == v13.mode_exit_trail
    assert v15.mode_switch_cooldown_days == v13.mode_switch_cooldown_days
    assert v15.risk_override_enabled is True
    assert v15.mild_defense_dd == v13.mild_defense_dd
    assert v15.harsh_defense_dd == v13.harsh_defense_dd


def test_v13_still_uses_60_long_windows():
    cfg = StructureGateConfig.v13()
    assert cfg.sticky_trail_days == 60
    assert cfg.strong_lookback == 60
    assert cfg.ers_lag_lookback == 60
