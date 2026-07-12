"""AI判断エンジン。

現時点ではEMA/RSI/MACDを組み合わせたルールベースの判断のみを実装している。
将来OpenAI APIやClaude APIによるLLM判断に差し替えられるよう、判断ロジックを
`AIEngine` という共通インターフェースの背後に隠蔽している。

差し替え方法:
    1. AIEngine を継承したクラス(例: OpenAIEngine, ClaudeEngine)を実装し、
       decide(df) -> Signal を実装する。
    2. get_ai_engine() のファクトリに名前を登録する。
    3. config.AI_ENGINE (または .env の AI_ENGINE) を切り替える。
   main.py 側の呼び出しコードは一切変更不要。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

import config

Action = Literal["BUY", "SELL", "WAIT"]


@dataclass
class Signal:
    """AIエンジンが返す売買判断。

    confidenceは統計的な確率ではなく、判断条件のうちいくつが満たされたかを
    0-100で表したヒューリスティックな指標(RuleBasedAIEngine参照)。
    """

    action: Action
    reason: str
    details: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


class AIEngine(ABC):
    """AI判断エンジンの共通インターフェース。"""

    @abstractmethod
    def decide(self, df: pd.DataFrame) -> Signal:
        """指標付きのローソク足DataFrameを受け取り、売買判断を返す。"""
        raise NotImplementedError


class RuleBasedAIEngine(AIEngine):
    """EMAトレンド + MACDモメンタム + RSIフィルターによるルールベース判断。"""

    def decide(self, df: pd.DataFrame) -> Signal:
        if df.empty:
            return Signal("WAIT", "ローソク足データが空です", {})

        latest = df.iloc[-1]
        required = ("close", "ema_fast", "ema_slow", "rsi", "macd", "macd_signal", "macd_hist")
        missing = [col for col in required if col not in df.columns or pd.isna(latest[col])]
        if missing:
            return Signal("WAIT", f"指標が未計算です: {missing}", {})

        details = {col: float(latest[col]) for col in required}

        uptrend = latest["ema_fast"] > latest["ema_slow"]
        downtrend = latest["ema_fast"] < latest["ema_slow"]
        macd_bullish = latest["macd_hist"] > 0
        macd_bearish = latest["macd_hist"] < 0
        rsi_not_overbought = latest["rsi"] < config.RSI_OVERBOUGHT
        rsi_not_oversold = latest["rsi"] > config.RSI_OVERSOLD

        # confidence = 3条件(トレンド/MACD/RSI)のうち満たされた数の割合(0/33/66/100)。
        # 統計的な確率ではなく、ルールがどれだけ揃っているかを表すだけの指標。
        buy_confidence = round(sum([uptrend, macd_bullish, rsi_not_overbought]) / 3 * 100)
        sell_confidence = round(sum([downtrend, macd_bearish, rsi_not_oversold]) / 3 * 100)

        if uptrend and macd_bullish and rsi_not_overbought:
            return Signal("BUY", "上昇トレンド + MACD陽転 + RSI過熱なし", details, buy_confidence)

        if downtrend and macd_bearish and rsi_not_oversold:
            return Signal("SELL", "下降トレンド + MACD陰転 + RSI売られすぎなし", details, sell_confidence)

        return Signal(
            "WAIT",
            "トレンド・モメンタムの条件が揃っていません",
            details,
            max(buy_confidence, sell_confidence),
        )


class UnavailableAIEngine(AIEngine):
    """未実装のエンジン名が指定された場合のプレースホルダー。"""

    def __init__(self, name: str) -> None:
        self._name = name

    def decide(self, df: pd.DataFrame) -> Signal:
        raise NotImplementedError(
            f"AIエンジン '{self._name}' は未実装です。ai_engine.py にクラスを実装し、"
            "get_ai_engine() に登録してください。"
        )


def get_ai_engine(engine_name: str | None = None) -> AIEngine:
    """設定に応じたAIEngineインスタンスを返すファクトリ関数。"""
    name = (engine_name or config.AI_ENGINE).lower()

    if name == "rule_based":
        return RuleBasedAIEngine()

    # 将来の拡張ポイント:
    # if name == "openai":
    #     return OpenAIEngine()
    # if name == "claude":
    #     return ClaudeEngine()

    return UnavailableAIEngine(name)
