"""Unit tests for Structure Gate v17 grinding-bear defense."""

from __future__ import annotations

from qresearch.strategy.structure_gate import StructureGateConfig


def test_v17_tighter_harsh_dd_and_sticky_pierce():
    cfg = StructureGateConfig.v17()
    assert cfg.harsh_defense_dd == 0.10
    assert cfg.harsh_dd_pierces_sticky is True
    assert cfg.thrust_overrides_dd_harsh is True


def test_v13_keeps_legacy_sticky_vs_harsh_dd():
    cfg = StructureGateConfig.v13()
    assert cfg.harsh_defense_dd == 0.20
    assert cfg.harsh_dd_pierces_sticky is False
    assert cfg.thrust_overrides_dd_harsh is True
