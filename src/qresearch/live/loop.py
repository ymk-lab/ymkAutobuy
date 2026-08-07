"""Live trading loop: feed → signal → risk budget → broker orders."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from qresearch.data.panel import panel_close
from qresearch.execution.adapter import BrokerAdapter
from qresearch.execution.targets import TargetWeightExecutor
from qresearch.execution.types import Fill
from qresearch.live.feed import Bar, MarketDataFeed
from qresearch.portfolio.risk import RiskBudgetConfig, allocate_risk_budget
from qresearch.strategy.multi import MultiAssetStrategy


@dataclass(frozen=True)
class LiveConfig:
    min_history: int = 60
    rebalance_every: int = 1
    max_drawdown: float = 0.25
    flatten_on_stop: bool = True


@dataclass
class LiveRunResult:
    equity: pd.Series
    cash: pd.Series
    weights: pd.DataFrame
    target_weights: pd.DataFrame
    fills: list[Fill]
    stopped: bool = False
    stop_reason: str | None = None
    bars_processed: int = 0

    def summary(self) -> pd.Series:
        eq = self.equity
        if eq.empty:
            return pd.Series(dtype=float)
        total_return = float(eq.iloc[-1] / eq.iloc[0] - 1.0)
        return pd.Series(
            {
                "total_return": total_return,
                "final_equity": float(eq.iloc[-1]),
                "max_equity": float(eq.max()),
                "min_equity": float(eq.min()),
                "n_fills": float(len(self.fills)),
                "bars_processed": float(self.bars_processed),
                "stopped": float(self.stopped),
            }
        )


@dataclass
class LiveTradingLoop:
    """Event loop bridging research strategies to an execution adapter.

    Next-bar protocol:
    - on bar t close: decide target weights (signal + risk budget)
    - on bar t+1: execute pending targets via broker, then decide again
    """

    feed: MarketDataFeed
    strategy: MultiAssetStrategy
    broker: BrokerAdapter
    risk_config: RiskBudgetConfig = field(default_factory=RiskBudgetConfig)
    config: LiveConfig = field(default_factory=LiveConfig)

    def run(self) -> LiveRunResult:
        executor = TargetWeightExecutor(self.broker)
        history: dict[str, list[dict]] = {}
        pending: dict[str, float] | None = None

        equity_rows: list[tuple[pd.Timestamp, float]] = []
        cash_rows: list[tuple[pd.Timestamp, float]] = []
        weight_rows: list[dict] = []
        target_rows: list[dict] = []
        fills: list[Fill] = []

        peak_equity: float | None = None
        stopped = False
        stop_reason: str | None = None
        bars = 0
        decisions = 0
        last_target: dict[str, float] = {}

        for batch in self.feed:
            if not batch:
                continue
            ts = next(iter(batch.values())).timestamp
            closes = {sym: bar.close for sym, bar in batch.items()}
            bars += 1

            # 1) Execute pending targets from prior decision (next-bar fill).
            if pending is not None:
                new_fills = executor.rebalance(pending, closes, ts)
                fills.extend(new_fills)
                pending = None

            # 2) Append bars into rolling history.
            self._append_batch(history, batch)
            hist_len = len(next(iter(history.values())))

            # 3) Mark equity / risk kill-switch.
            equity = self.broker.get_equity(closes)
            if peak_equity is None or equity > peak_equity:
                peak_equity = equity
            dd = equity / peak_equity - 1.0 if peak_equity else 0.0
            if dd <= -abs(self.config.max_drawdown):
                stopped = True
                stop_reason = f"max_drawdown:{dd:.4f}"
                if self.config.flatten_on_stop:
                    flat_fills = executor.rebalance(
                        {sym: 0.0 for sym in closes}, closes, ts
                    )
                    fills.extend(flat_fills)
                    equity = self.broker.get_equity(closes)

            # 4) Record state
            positions = self.broker.get_positions()
            pos_weights = self._positions_to_weights(positions, closes, equity)
            equity_rows.append((ts, equity))
            cash_rows.append((ts, self.broker.get_cash()))
            weight_rows.append({"datetime": ts, **pos_weights})

            if stopped:
                target_rows.append({"datetime": ts, **{s: 0.0 for s in closes}})
                break

            # 5) Decide new targets for next bar when history is warm.
            if not last_target:
                last_target = {s: 0.0 for s in closes}
            target = dict(last_target)
            if hist_len >= self.config.min_history:
                if decisions % max(self.config.rebalance_every, 1) == 0:
                    panel = self._history_to_panel(history)
                    signals = self.strategy.generate_signals(panel)
                    closes_df = panel_close(panel)
                    weights = allocate_risk_budget(
                        signals, closes_df, self.risk_config
                    )
                    last = weights.iloc[-1]
                    target = {str(k): float(v) for k, v in last.items()}
                    # Ensure zeros for symbols missing from weight frame.
                    for s in closes:
                        target.setdefault(s, 0.0)
                    pending = target
                    last_target = target
                decisions += 1

            target_rows.append({"datetime": ts, **target})

        equity = pd.Series(
            {t: v for t, v in equity_rows}, dtype=float, name="equity"
        ).sort_index()
        cash = pd.Series(
            {t: v for t, v in cash_rows}, dtype=float, name="cash"
        ).sort_index()
        weights = pd.DataFrame(weight_rows).set_index("datetime").sort_index()
        targets = pd.DataFrame(target_rows).set_index("datetime").sort_index()

        return LiveRunResult(
            equity=equity,
            cash=cash,
            weights=weights,
            target_weights=targets,
            fills=fills,
            stopped=stopped,
            stop_reason=stop_reason,
            bars_processed=bars,
        )

    @staticmethod
    def _append_batch(history: dict[str, list[dict]], batch: dict[str, Bar]) -> None:
        for sym, bar in batch.items():
            history.setdefault(sym, []).append(
                {
                    "datetime": bar.timestamp,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
            )

    @staticmethod
    def _history_to_panel(history: dict[str, list[dict]]) -> dict[str, pd.DataFrame]:
        panel: dict[str, pd.DataFrame] = {}
        for sym, rows in history.items():
            df = pd.DataFrame(rows).set_index("datetime").sort_index()
            panel[sym] = df
        return panel

    @staticmethod
    def _positions_to_weights(
        positions: dict[str, float],
        prices: dict[str, float],
        equity: float,
    ) -> dict[str, float]:
        if equity <= 0:
            return {s: 0.0 for s in prices}
        out = {s: 0.0 for s in prices}
        for sym, qty in positions.items():
            px = prices.get(sym)
            if px is None or pd.isna(px):
                continue
            out[sym] = float(qty) * float(px) / equity
        return out
