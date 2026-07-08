"""indicators.py の単体テスト。MT5への接続なしで実行できる。"""
from __future__ import annotations

import numpy as np
import pandas as pd

import indicators


def _sample_close_series(n: int = 60) -> pd.Series:
    rng = np.random.default_rng(seed=42)
    steps = rng.normal(loc=0.0, scale=0.5, size=n)
    prices = 150.0 + np.cumsum(steps)
    return pd.Series(prices, name="close")


def test_ema_length_matches_input():
    close = _sample_close_series()
    result = indicators.ema(close, period=10)
    assert len(result) == len(close)


def test_rsi_within_bounds():
    close = _sample_close_series()
    result = indicators.rsi(close, period=14)
    valid = result.dropna()
    assert (valid >= 0).all()
    assert (valid <= 100).all()


def test_macd_histogram_equals_macd_minus_signal():
    close = _sample_close_series()
    macd_df = indicators.macd(close)
    diff = macd_df["macd"] - macd_df["macd_signal"] - macd_df["macd_hist"]
    assert np.allclose(diff, 0.0)


def test_add_indicators_adds_expected_columns():
    df = pd.DataFrame({"close": _sample_close_series()})
    result = indicators.add_indicators(df)
    for column in ["ema_fast", "ema_slow", "rsi", "macd", "macd_signal", "macd_hist"]:
        assert column in result.columns


def test_add_indicators_requires_close_column():
    df = pd.DataFrame({"price": _sample_close_series()})
    try:
        indicators.add_indicators(df)
        assert False, "ValueErrorが送出されるべき"
    except ValueError:
        pass
