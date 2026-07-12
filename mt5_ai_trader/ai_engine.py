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

import json
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


class CandleThrottledEngine(AIEngine):
    """内部エンジンのdecide()を、ローソク足が変わったときだけ呼び出すラッパー。

    main.pyの監視ループはLOOP_INTERVAL_SECONDS(既定60秒)ごとに毎サイクル
    decide()を呼ぶが、TIMEFRAME(例: M15)のローソク足はもっと長い間隔でしか
    更新されない。OpenAI/ClaudeのようにAPI呼び出しにコストがかかるエンジンで
    毎サイクル呼んでしまうと、同じローソク足に対して何度も課金してしまう
    (例: LOOP_INTERVAL_SECONDS=60・TIMEFRAME=M15なら本来15回に14回は無駄)。

    直近のローソク足(df末尾の"time"列)が前回decide()を呼んだときと同じ
    場合は、内部エンジンを呼ばずキャッシュした前回の判断をそのまま返す。
    ローソク足が変わったとき(=TIMEFRAME分ごとに1回)だけ実際にAPIを呼ぶ。
    """

    def __init__(self, inner: AIEngine) -> None:
        self._inner = inner
        self._last_candle_time: Any = None
        self._cached_signal: Signal | None = None

    def decide(self, df: pd.DataFrame) -> Signal:
        if df.empty or "time" not in df.columns:
            return self._inner.decide(df)

        latest_time = df.iloc[-1]["time"]

        if self._cached_signal is not None and latest_time == self._last_candle_time:
            cached = self._cached_signal
            return Signal(
                cached.action,
                f"{cached.reason}(このローソク足では既に判断済みのため再利用・API未呼び出し)",
                cached.details,
                cached.confidence,
            )

        signal = self._inner.decide(df)
        self._last_candle_time = latest_time
        self._cached_signal = signal
        return signal


def describe_market_conditions(df: pd.DataFrame, symbol: str, timeframe: str) -> str:
    """LLM判断エンジン(OpenAIEngine/ClaudeEngine)向けに、直近の指標状況を
    テキスト化する。RuleBasedAIEngineが使うのと同じ指標(EMA/RSI/MACD)を
    渡すことで、判断材料をルールベースと揃えている。
    """
    latest = df.iloc[-1]
    recent_closes = [round(float(v), 5) for v in df["close"].tail(10).tolist()]
    return (
        f"銘柄: {symbol} / 時間足: {timeframe}\n"
        f"直近の終値(古い順、最大10件): {recent_closes}\n"
        f"現在値(close): {latest.get('close')}\n"
        f"EMA(短期): {latest.get('ema_fast')}\n"
        f"EMA(長期): {latest.get('ema_slow')}\n"
        f"RSI: {latest.get('rsi')}\n"
        f"MACD: {latest.get('macd')}\n"
        f"MACDシグナル: {latest.get('macd_signal')}\n"
        f"MACDヒストグラム: {latest.get('macd_hist')}\n"
    )


LLM_SYSTEM_PROMPT = (
    "あなたはFXトレードの判断アシスタントです。与えられたテクニカル指標のみに基づいて "
    "BUY・SELL・WAITのいずれかを判断してください。根拠が不十分、あるいは指標が矛盾して "
    "いる場合は必ずWAITを選んでください。断定的すぎる判断は避けてください。"
    "出力は次の形式のJSONオブジェクトのみとし、それ以外の文章(前置き・コードブロック等)は"
    '一切含めないでください: {"action": "BUY", "reason": "短い理由(日本語)", "confidence": 0から100の整数}'
)


def parse_llm_signal_json(content: str) -> Signal:
    """LLMの応答文字列からSignalを組み立てる。

    応答の前後に余分な文章が付いていても、最初の"{"から最後の"}"までを
    JSONとして解釈を試みる。action/confidenceが不正な場合はValueErrorを
    送出する(呼び出し側でWAITにフォールバックすることを想定)。
    """
    text = content.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("JSON形式のレスポンスが見つかりませんでした")

    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSONの解析に失敗しました: {exc}") from exc

    action = str(data.get("action", "")).upper()
    if action not in ("BUY", "SELL", "WAIT"):
        raise ValueError(f"不正なaction値です: {action!r}")

    reason = str(data.get("reason") or "(理由なし)")

    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(100.0, confidence))

    return Signal(action, reason, {}, confidence)  # type: ignore[arg-type]


def get_ai_engine(engine_name: str | None = None) -> AIEngine:
    """設定に応じたAIEngineインスタンスを返すファクトリ関数。"""
    name = (engine_name or config.AI_ENGINE).lower()

    if name == "rule_based":
        return RuleBasedAIEngine()
    if name == "openai":
        from openai_engine import OpenAIEngine  # 遅延import(循環import回避・rule_based運用時の余分な依存を避けるため)

        # CandleThrottledEngineで包み、ローソク足が変わったときだけAPIを呼ぶ
        # ようにする(コスト対策。CandleThrottledEngineのdocstring参照)。
        return CandleThrottledEngine(OpenAIEngine())
    if name == "claude":
        from claude_engine import ClaudeEngine  # 遅延import(理由は上と同じ)

        return CandleThrottledEngine(ClaudeEngine())

    return UnavailableAIEngine(name)
