from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from qresearch.data.loader import load_ohlcv_csv, save_ohlcv_csv, validate_ohlcv
from qresearch.data.synthetic import generate_synthetic_ohlcv


def test_save_and_load_roundtrip(tmp_path: Path):
    data = generate_synthetic_ohlcv(n=60, seed=11)
    path = save_ohlcv_csv(data, tmp_path / "x.csv")
    loaded = load_ohlcv_csv(path)
    pd.testing.assert_frame_equal(loaded, validate_ohlcv(data), check_freq=False)


def test_load_with_aliases(tmp_path: Path):
    data = generate_synthetic_ohlcv(n=40, seed=12)
    raw = data.reset_index()
    raw.columns = ["Date", "Open", "High", "Low", "Close", "Volume"]
    path = tmp_path / "aliased.csv"
    raw.to_csv(path, index=False)

    loaded = load_ohlcv_csv(path)
    assert list(loaded.columns) == ["open", "high", "low", "close", "volume"]
    assert len(loaded) == 40


def test_load_parse_index(tmp_path: Path):
    data = generate_synthetic_ohlcv(n=30, seed=13)
    path = tmp_path / "indexed.csv"
    data.to_csv(path)
    loaded = load_ohlcv_csv(path, parse_index=True)
    assert len(loaded) == 30


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_ohlcv_csv("/tmp/does_not_exist_qresearch.csv")
