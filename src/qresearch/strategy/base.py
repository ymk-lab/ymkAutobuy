"""Strategy interface for research backtests."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    """Base strategy.

    `generate_signals` must return a target weight series aligned to `data.index`.
    Values are typically in [-1, 1]:
    - +1: full long
    -  0: flat
    - -1: full short
    """

    name: str = "strategy"

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        raise NotImplementedError

    def generate_regimes(self, data: pd.DataFrame) -> pd.Series | None:
        """Optional regime labels aligned to `data.index`."""
        return None
