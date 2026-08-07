"""Paper trading broker aligned with research backtest assumptions."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from qresearch.backtest.costs import CostModel


@dataclass
class PaperState:
    equity: float
    weights: dict[str, float]
    prev_close: dict[str, float]
    realized_costs: float = 0.0
    equity_curve: list[tuple[pd.Timestamp, float]] = field(default_factory=list)


class PaperBroker:
    """Stateful paper broker using research next-bar conventions.

    Research-aligned bar protocol:
    1) `queue_targets(weights)` after signal decision (bar t close)
    2) `process_bar(t+1, open, close)` fills pending at open and marks to close

    Return model matches `MultiBacktestEngine`:
    new weights earn close-to-close, minus turnover * cost_rate.
    """

    def __init__(
        self,
        *,
        initial_capital: float = 100_000.0,
        cost_model: CostModel | None = None,
        symbols: list[str] | None = None,
    ) -> None:
        self.initial_capital = initial_capital
        self.cost_model = cost_model or CostModel()
        self.symbols = list(symbols or [])
        self._pending: dict[str, float] | None = None
        self.state = PaperState(
            equity=initial_capital,
            weights={s: 0.0 for s in self.symbols},
            prev_close={s: float("nan") for s in self.symbols},
        )

    def queue_targets(self, targets: dict[str, float] | pd.Series) -> None:
        if isinstance(targets, pd.Series):
            targets = targets.to_dict()
        pending = {s: 0.0 for s in self.symbols}
        for k, v in targets.items():
            sym = str(k)
            pending[sym] = float(v)
            if sym not in self.state.weights:
                self.symbols.append(sym)
                self.state.weights[sym] = 0.0
                self.state.prev_close[sym] = float("nan")
        self._pending = pending

    def process_bar(
        self,
        timestamp: pd.Timestamp,
        close_prices: dict[str, float],
        *,
        open_prices: dict[str, float] | None = None,
    ) -> float:
        """Fill pending targets and apply close-to-close portfolio return.

        `open_prices` accepted for API symmetry / live logs; return math uses
        close-to-close to stay aligned with the vectorized engines.
        """
        del open_prices  # research alignment uses close-to-close
        if self._pending is not None:
            new_w = self._pending
            turnover = sum(
                abs(new_w.get(s, 0.0) - self.state.weights.get(s, 0.0))
                for s in set(new_w) | set(self.state.weights)
            )
            self.state.weights = {s: float(new_w.get(s, 0.0)) for s in self.symbols}
            self._pending = None
        else:
            turnover = 0.0

        port_ret = 0.0
        for sym, w in self.state.weights.items():
            prev = self.state.prev_close.get(sym)
            px = close_prices.get(sym)
            if (
                w != 0.0
                and prev is not None
                and px is not None
                and pd.notna(prev)
                and pd.notna(px)
                and prev > 0
            ):
                port_ret += w * (float(px) / float(prev) - 1.0)

        cost = turnover * self.cost_model.cost_rate()
        net = port_ret - cost
        self.state.equity *= 1.0 + net
        self.state.realized_costs += cost
        self.state.equity_curve.append((pd.Timestamp(timestamp), self.state.equity))

        for sym, px in close_prices.items():
            if px is not None and pd.notna(px):
                self.state.prev_close[str(sym)] = float(px)
        return net

    def equity_series(self) -> pd.Series:
        if not self.state.equity_curve:
            return pd.Series(dtype=float, name="paper_equity")
        idx, vals = zip(*self.state.equity_curve)
        return pd.Series(vals, index=pd.DatetimeIndex(idx), name="paper_equity")


def replay_paper_from_weights(
    weights: pd.DataFrame,
    closes: pd.DataFrame,
    *,
    opens: pd.DataFrame | None = None,
    initial_capital: float = 100_000.0,
    cost_model: CostModel | None = None,
) -> pd.Series:
    """Replay execution weights through PaperBroker for alignment checks."""
    broker = PaperBroker(
        initial_capital=initial_capital,
        cost_model=cost_model,
        symbols=list(weights.columns),
    )
    for ts in weights.index:
        broker.queue_targets(weights.loc[ts])
        close_px = {c: float(closes.loc[ts, c]) for c in weights.columns}
        open_px = (
            {c: float(opens.loc[ts, c]) for c in weights.columns}
            if opens is not None
            else None
        )
        broker.process_bar(ts, close_px, open_prices=open_px)
    return broker.equity_series()
