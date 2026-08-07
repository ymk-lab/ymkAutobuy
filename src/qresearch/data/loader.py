"""OHLCV data loading and point-in-time safety checks."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")

# Common vendor / exchange aliases → canonical names
COLUMN_ALIASES: dict[str, str] = {
    "date": "datetime",
    "time": "datetime",
    "timestamp": "datetime",
    "datetime": "datetime",
    "dt": "datetime",
    "o": "open",
    "h": "high",
    "l": "low",
    "c": "close",
    "v": "volume",
    "vol": "volume",
    "adj_close": "close",
    "adjclose": "close",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
}


def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize an OHLCV frame.

    Ensures:
    - required columns exist
    - datetime index is sorted and unique
    - OHLC relationships are sane
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

    if out[list(REQUIRED_COLUMNS)].isna().any().any():
        raise ValueError("OHLCV contains NaN values")
    if (out[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Prices must be positive")
    if (out["volume"] < 0).any():
        raise ValueError("volume must be >= 0")
    if (out["high"] < out[["open", "close"]].max(axis=1)).any():
        raise ValueError("high must be >= open/close")
    if (out["low"] > out[["open", "close"]].min(axis=1)).any():
        raise ValueError("low must be <= open/close")

    out.index.name = "datetime"
    return out


def _normalize_columns(columns: pd.Index) -> list[str]:
    normalized: list[str] = []
    for col in columns:
        key = str(col).strip().lower().replace(" ", "_")
        normalized.append(COLUMN_ALIASES.get(key, key))
    return normalized


def load_ohlcv_csv(
    path: str | Path,
    *,
    datetime_col: str | None = None,
    tz: str | None = None,
    parse_index: bool = False,
) -> pd.DataFrame:
    """Load OHLCV CSV into a validated frame.

    Accepts either:
    - a datetime column (auto-detected from aliases if `datetime_col` is None)
    - or datetime already stored as the first/index column (`parse_index=True`)
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    if parse_index:
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        frame.columns = _normalize_columns(frame.columns)
        if not isinstance(frame.index, pd.DatetimeIndex):
            frame.index = pd.to_datetime(frame.index, utc=False)
    else:
        frame = pd.read_csv(path)
        frame.columns = _normalize_columns(frame.columns)
        col = datetime_col
        if col is not None:
            col = COLUMN_ALIASES.get(col.strip().lower(), col.strip().lower())
        if col is None:
            if "datetime" in frame.columns:
                col = "datetime"
            else:
                raise ValueError(
                    "CSV missing datetime column; pass datetime_col=... or parse_index=True"
                )
        if col not in frame.columns:
            raise ValueError(f"CSV missing datetime column: {col}")

        idx = pd.to_datetime(frame[col], utc=False)
        frame = frame.drop(columns=[col])
        frame.index = pd.DatetimeIndex(idx, name="datetime")

    if tz is not None:
        if frame.index.tz is None:
            frame.index = frame.index.tz_localize(tz)
        else:
            frame.index = frame.index.tz_convert(tz)

    return validate_ohlcv(frame)


def save_ohlcv_csv(df: pd.DataFrame, path: str | Path) -> Path:
    """Persist validated OHLCV to CSV with a `datetime` column."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = validate_ohlcv(df).copy()
    out = out.reset_index()
    if out.columns[0] != "datetime":
        out = out.rename(columns={out.columns[0]: "datetime"})
    out.to_csv(path, index=False)
    return path
