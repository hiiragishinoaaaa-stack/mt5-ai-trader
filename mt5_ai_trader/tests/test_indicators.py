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


def _trending_ohlc(n: int = 60) -> pd.DataFrame:
    """一方向に強く上昇し続ける(高値安値の幅は小さい)、明確なトレンド相場のOHLC。"""
    close = 150.0 + np.arange(n, dtype=float) * 0.3
    return pd.DataFrame({"close": close, "high": close + 0.05, "low": close - 0.05})


def _ranging_ohlc(n: int = 60) -> pd.DataFrame:
    """一定の範囲内を行ったり来たりする、方向感の無いレンジ相場のOHLC。"""
    close = 150.0 + np.sin(np.arange(n) * 0.5) * 0.3
    return pd.DataFrame({"close": close, "high": close + 0.05, "low": close - 0.05})


def test_adx_length_matches_input():
    df = _trending_ohlc()
    result = indicators.adx(df, period=14)
    assert len(result) == len(df)


def test_adx_within_bounds():
    df = _trending_ohlc()
    result = indicators.adx(df, period=14)
    valid = result.dropna()
    assert (valid >= 0).all()
    assert (valid <= 100).all()


def test_adx_higher_for_strong_trend_than_range():
    trending = indicators.adx(_trending_ohlc(), period=14).iloc[-1]
    ranging = indicators.adx(_ranging_ohlc(), period=14).iloc[-1]
    assert trending > ranging


def test_add_indicators_adds_adx_when_high_low_present():
    result = indicators.add_indicators(_trending_ohlc())
    assert "adx" in result.columns
    assert "atr" in result.columns


def test_add_indicators_omits_adx_without_high_low():
    df = pd.DataFrame({"close": _sample_close_series()})
    result = indicators.add_indicators(df)
    assert "adx" not in result.columns
