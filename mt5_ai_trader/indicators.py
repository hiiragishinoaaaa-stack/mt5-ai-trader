"""テクニカル指標(EMA / RSI / MACD)の計算ロジック。

外部のテクニカル指標ライブラリ(TA-Lib等)には依存せず、pandasのみで
計算する。関数はいずれも純粋関数で、MT5やAIエンジンの知識を持たない
ため、単体テストや将来の指標追加が容易になっている。
"""
from __future__ import annotations

import pandas as pd

import config


def ema(series: pd.Series, period: int) -> pd.Series:
    """指数移動平均(EMA)を計算する。"""
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI(Relative Strength Index)をワイルダー法で計算する。"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi_value = 100 - (100 / (1 + rs))
    # 下落が全くない(avg_loss == 0)区間はRSI=100として扱う
    rsi_value = rsi_value.where(avg_loss != 0, 100.0)
    return rsi_value


def macd(
    series: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> pd.DataFrame:
    """MACDライン・シグナルライン・ヒストグラムを計算する。"""
    ema_fast = ema(series, fast_period)
    ema_slow = ema(series, slow_period)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal_period)
    histogram = macd_line - signal_line

    return pd.DataFrame(
        {
            "macd": macd_line,
            "macd_signal": signal_line,
            "macd_hist": histogram,
        }
    )


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR(Average True Range)をワイルダー法で計算する。high/low/close列が必要。"""
    prev_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """ローソク足DataFrame(close列必須)に指標列を追加したコピーを返す。

    high/low列がある場合はATRも計算する(無い場合はatr列を追加しない。
    RuleBasedAIEngineがATR必須条件を評価する際に指標未計算として扱う)。
    """
    if "close" not in df.columns:
        raise ValueError("DataFrameに'close'列が必要です")

    result = df.copy()
    result["ema_fast"] = ema(result["close"], config.EMA_FAST_PERIOD)
    result["ema_slow"] = ema(result["close"], config.EMA_SLOW_PERIOD)
    result["rsi"] = rsi(result["close"], config.RSI_PERIOD)

    macd_df = macd(
        result["close"],
        config.MACD_FAST_PERIOD,
        config.MACD_SLOW_PERIOD,
        config.MACD_SIGNAL_PERIOD,
    )
    result = pd.concat([result, macd_df], axis=1)

    if "high" in result.columns and "low" in result.columns:
        result["atr"] = atr(result, config.ATR_PERIOD)

    return result
