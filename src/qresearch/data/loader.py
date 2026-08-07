"""OHLCV data loading and point-in-time safety checks."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize an OHLCV frame.

    Ensures:
    - required columns exist
    - datetime index is sorted and unique
    - no look-ahead friendly future timestamps mixed in
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {missing}")

    out = df[list(REQUIRED_COLUMNS)].copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        raise TypeError("OHLCV index must be a DatetimeIndex")

    if out.index.hasnans:
        raise ValueError("OHLCV index contains NaT")
    if not out.index.is_monotonic_increasing:
        out = out.sort_index()
    if out.index.has_duplicates:
        raise ValueError("OHLCV index has duplicate timestamps")

    if (out[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Prices must be positive")
    if (out["high"] < out[["open", "close"]].max(axis=1)).any():
        raise ValueError("high must be >= open/close")
    if (out["low"] > out[["open", "close"]].min(axis=1)).any():
        raise ValueError("low must be <= open/close")

    return out


def load_ohlcv_csv(
    path: str | Path,
    *,
    datetime_col: str = "datetime",
    tz: str | None = None,
) -> pd.DataFrame:
    """Load OHLCV CSV with a datetime column into a validated frame."""
    frame = pd.read_csv(path)
    if datetime_col not in frame.columns:
        raise ValueError(f"CSV missing datetime column: {datetime_col}")

    idx = pd.to_datetime(frame[datetime_col], utc=False)
    if tz is not None:
        if idx.dt.tz is None:
            idx = idx.dt.tz_localize(tz)
        else:
            idx = idx.dt.tz_convert(tz)

    frame = frame.drop(columns=[datetime_col])
    frame.index = pd.DatetimeIndex(idx, name="datetime")
    frame.columns = [c.strip().lower() for c in frame.columns]
    return validate_ohlcv(frame)
