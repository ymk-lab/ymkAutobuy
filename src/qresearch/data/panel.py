"""Multi-asset OHLCV panel helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from qresearch.data.loader import load_ohlcv_csv, validate_ohlcv


def align_panel(
    frames: dict[str, pd.DataFrame],
    *,
    how: str = "inner",
) -> dict[str, pd.DataFrame]:
    """Validate each leg and align calendars.

    `how="inner"` keeps only shared timestamps (research-safe default).
    """
    if not frames:
        raise ValueError("frames must be non-empty")

    cleaned = {sym: validate_ohlcv(df) for sym, df in frames.items()}
    index = None
    for df in cleaned.values():
        index = df.index if index is None else index.join(df.index, how=how)
    if index is None or len(index) == 0:
        raise ValueError("aligned panel is empty")

    return {sym: df.reindex(index) for sym, df in cleaned.items()}


def panel_close(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Wide close matrix: index=datetime, columns=symbols."""
    return pd.DataFrame({sym: df["close"] for sym, df in panel.items()})


def panel_open(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame({sym: df["open"] for sym, df in panel.items()})


def load_panel_csv_dir(
    directory: str | Path,
    *,
    pattern: str = "*.csv",
) -> dict[str, pd.DataFrame]:
    """Load `SYMBOL.csv` files from a directory into an aligned panel."""
    directory = Path(directory)
    paths = sorted(directory.glob(pattern))
    if not paths:
        raise FileNotFoundError(f"no CSV files matching {pattern} in {directory}")
    frames = {p.stem.upper(): load_ohlcv_csv(p) for p in paths}
    return align_panel(frames)


def save_panel_csv_dir(panel: dict[str, pd.DataFrame], directory: str | Path) -> Path:
    """Save each symbol as `SYMBOL.csv` under directory."""
    from qresearch.data.loader import save_ohlcv_csv

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for sym, df in panel.items():
        save_ohlcv_csv(df, directory / f"{sym.upper()}.csv")
    return directory


def generate_synthetic_panel(
    symbols: tuple[str, ...] = ("AAA", "BBB", "CCC"),
    n: int = 750,
    *,
    start: str = "2022-01-01",
    seed: int = 7,
) -> dict[str, pd.DataFrame]:
    """Correlated synthetic multi-asset daily OHLCV panel."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start=start, periods=n)
    k = len(symbols)

    # Factor model: common market + idiosyncratic noise
    market = rng.normal(0.0002, 0.01, size=n)
    betas = rng.uniform(0.6, 1.3, size=k)
    idio = rng.normal(0.0, 0.012, size=(n, k))
    rets = market[:, None] * betas[None, :] + idio

    panel: dict[str, pd.DataFrame] = {}
    for j, sym in enumerate(symbols):
        close = 100 * np.exp(np.cumsum(rets[:, j]))
        open_ = np.concatenate([[close[0]], close[:-1]])
        noise = rng.uniform(0.001, 0.005, size=n)
        high = np.maximum(open_, close) * (1 + noise)
        low = np.minimum(open_, close) * (1 - noise)
        volume = rng.integers(80_000, 400_000, size=n).astype(float)
        panel[sym] = validate_ohlcv(
            pd.DataFrame(
                {
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                },
                index=idx,
            )
        )
    return panel
