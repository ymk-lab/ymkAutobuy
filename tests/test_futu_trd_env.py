"""Live-book lock: REAL follows FUTU_TRD_ENV and still refuses without ALLOW_LIVE."""

from __future__ import annotations

import sys

import pytest

from qresearch.brokers.futu.adapter import FutuBrokerAdapter
from qresearch.brokers.futu.config import configured_trd_env, futu_trd_env_simulate


def test_default_trd_env_is_simulate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FUTU_TRD_ENV", raising=False)
    assert futu_trd_env_simulate() is True
    assert configured_trd_env() == "SIMULATE"


def test_real_trd_env_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FUTU_TRD_ENV", "REAL")
    assert futu_trd_env_simulate() is False
    assert configured_trd_env() == "REAL"


def test_adapter_refuses_real_without_allow_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QRESEARCH_FUTU_ALLOW_LIVE", "0")
    with pytest.raises(ValueError, match="ALLOW_LIVE"):
        FutuBrokerAdapter(dry_run=True, simulate=False)


def test_adapter_allows_real_when_allow_live_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QRESEARCH_FUTU_ALLOW_LIVE", "1")
    broker = FutuBrokerAdapter(dry_run=True, simulate=False)
    assert broker.simulate is False


def _install_fake_futu(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    mod = types.ModuleType("futu")
    mod.RET_OK = 0

    class Currency:
        USD = "USD"

    class TrdEnv:
        SIMULATE = "SIMULATE"
        REAL = "REAL"

    mod.Currency = Currency
    mod.TrdEnv = TrdEnv
    monkeypatch.setitem(sys.modules, "futu", mod)


def test_equity_uses_usd_marks_not_hkd_total_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    """HK OpenD total_assets is HKD; sizing must stay on USD cash + USD marks."""
    import pandas as pd

    _install_fake_futu(monkeypatch)

    class Ctx:
        def accinfo_query(self, trd_env=None, currency=None):  # noqa: ANN001
            if currency == "USD":
                return 0, pd.DataFrame([{"total_assets": 58_935.0, "us_cash": 26_641.7}])
            return 0, pd.DataFrame(
                [{"total_assets": 459_000.0, "us_cash": 26_641.7, "cash": 26_641.7}]
            )

        def position_list_query(self, trd_env=None):  # noqa: ANN001
            return 0, pd.DataFrame([{"code": "US.AMD", "qty": 50.0}])

    broker = FutuBrokerAdapter(trade_ctx=Ctx(), dry_run=True, simulate=True)
    eq = broker.get_equity({"AMD.US": 645.86})
    assert eq == pytest.approx(26_641.7 + 50 * 645.86)
    assert eq < 100_000


def test_equity_missing_mark_asks_for_usd_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    import pandas as pd

    _install_fake_futu(monkeypatch)
    seen: list[object] = []

    class Ctx:
        def accinfo_query(self, trd_env=None, currency=None):  # noqa: ANN001
            seen.append(currency)
            if currency == "USD":
                return 0, pd.DataFrame([{"total_assets": 58_935.0, "us_cash": 26_641.7}])
            return 0, pd.DataFrame([{"total_assets": 459_000.0, "us_cash": 26_641.7}])

        def position_list_query(self, trd_env=None):  # noqa: ANN001
            return 0, pd.DataFrame([{"code": "US.AMD", "qty": 50.0}])

    broker = FutuBrokerAdapter(trade_ctx=Ctx(), dry_run=True, simulate=True)
    eq = broker.get_equity({})
    assert eq == pytest.approx(58_935.0)
    assert "USD" in seen


def test_account_snapshot_reports_real_book(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FUTU_TRD_ENV", "REAL")
    monkeypatch.setenv("QRESEARCH_FUTU_ALLOW_LIVE", "1")

    class _Broker:
        simulate = False
        trade_ctx = None

        def get_cash(self) -> float:
            return 12.5

        def get_positions(self) -> dict[str, float]:
            return {}

        def snapshot_quotes(self, _syms: list[str]) -> dict[str, float]:
            return {}

        def close(self) -> None:
            return None

    def _from_opend(cls, **kwargs):  # noqa: ANN003
        assert kwargs.get("dry_run") is True
        assert kwargs.get("simulate", None) is None
        return _Broker()

    import qresearch.brokers.futu as futu_mod
    from qresearch.web.paper_app import _account_snapshot

    monkeypatch.setattr(futu_mod, "has_futu_opend", lambda: True)
    monkeypatch.setattr(futu_mod.FutuBrokerAdapter, "from_opend", classmethod(_from_opend))
    snap = _account_snapshot()
    assert snap["ok"] is True
    assert snap["trd_env"] == "REAL"
    assert snap["cash_usd"] == 12.5


def test_daily_job_refuses_real_without_allow_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FUTU_TRD_ENV", "REAL")
    monkeypatch.setenv("QRESEARCH_FUTU_ALLOW_LIVE", "0")
    monkeypatch.setenv("QRESEARCH_SG_PAPER_SUBMIT", "1")
    monkeypatch.setattr(sys, "argv", ["run_structure_gate_v13_paper_daily.py", "once"])

    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "examples" / "run_structure_gate_v13_paper_daily.py"
    spec = importlib.util.spec_from_file_location("sg_v13_daily_live_lock", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main() == 3
