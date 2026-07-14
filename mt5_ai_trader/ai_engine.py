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


_BONUS_CONDITION_COUNT = 5


class RuleBasedAIEngine(AIEngine):
    """必須条件(全て満たす必要がある) + 加点条件(2段階目のスコアリング)で
    BUY/SELL/WAITを判断するルールベースエンジン。「勝率優先」(取引回数より
    質を優先する)方針で設計されており、必須条件の時点でトレンド逆張り・
    高値掴み/安値売り・凪相場でのエントリーを排除し、その上で加点条件で
    さらに絞り込む。

    ENTRY_STRICTNESSプリセット(conservative/balanced/aggressive/active_m5、
    settings_schema.ENTRY_STRICTNESS_PRESETS参照)によって、RSI帯域や
    必要スコア・EMA/ATR期間・(conservativeのみ)直近5本の高安値フィルターが
    切り替わる。

    ## 必須条件(BUY)
    1. ema_fast > ema_slow(取引時間足での上昇トレンド)
    2. 上位足(H1)フィルター: H1のEMA(H1_EMA_FAST_PERIOD)がEMA
       (H1_EMA_SLOW_PERIOD)より上(H1データ不足で判定不能な場合は素通し)。
       下降トレンド中はこの時点でBUYが必ず弾かれる。
    3. 押し目からの回復(_pullback_ok参照): 直近PULLBACK_LOOKBACK_BARS本の
       間にEMA(短期)からPULLBACK_MIN_EXTENSION_ATR×ATR以上離れたことが
       あり、現在はPULLBACK_MAX_DISTANCE_ATR×ATR以内まで戻っている
       (EMAとの単純クロスだけでなく、値動きが十分あった上での押し目待ちに
       する)
    4. RSI_BUY_MIN <= rsi <= RSI_BUY_MAX(過熱・売られすぎの両端を除外)
    5. spread <= MAX_SPREAD_POINTS(MAX_SPREAD_POINTS<=0なら無効)
    6. ATR(points換算) >= ATR_MIN_POINTS(ATR_MIN_POINTS<=0なら無効。
       値動きが小さすぎるレンジ相場での無駄なエントリーを防ぐ)
    7. MACDヒストグラムが方向と一致(>0)
    8. MACDヒストグラムが前足よりその方向へ拡大(縮小中=勢い喪失時は除外)
    9. (REQUIRE_NO_NEW_EXTREME_5BARS有効時のみ)直近5本(最新を除く)の
       安値を更新していない
    SELLはBUYの左右対称(EMA/RSI/高安値・H1・押し目の向きが逆)。

    ## 加点条件(各1点、最大5点)
    1. EMA(短期)の傾きが方向と一致(前足より上/下)
    2. 直近ローソク足の実体が方向と一致(陽線/陰線)
    3. 直近3本の安値(BUY)/高値(SELL)がその方向へ切り上がって/切り下がっている
    4. RSIが50を方向側へ超えている(BUYなら>50、SELLなら<50。モメンタム確認)
    5. 上位足(H1)のEMA(短期)自体も方向に傾いている(H1判定不能時は付与しない)

    必須条件を全て満たし、加点スコアがREQUIRED_SCORE以上ならBUY/SELL、
    そうでなければWAITを返す。details には score/required_score/
    bonus_reasons/failed_required等を構造化して格納する(Dashboard表示用)。
    """

    def decide(self, df: pd.DataFrame) -> Signal:
        if df.empty:
            return Signal("WAIT", "ローソク足データが空です", {})

        required_cols = ("open", "close", "high", "low", "ema_fast", "ema_slow", "rsi", "macd_hist")
        latest = df.iloc[-1]
        missing = [col for col in required_cols if col not in df.columns or pd.isna(latest[col])]
        if missing:
            return Signal("WAIT", f"指標が未計算です: {missing}", {})

        details: dict[str, Any] = {col: float(latest[col]) for col in required_cols}
        if "atr" in df.columns and not pd.isna(latest["atr"]):
            details["atr"] = float(latest["atr"])
        if "spread" in df.columns and not pd.isna(latest["spread"]):
            details["spread"] = float(latest["spread"])

        spread_ok = self._spread_ok(latest)
        atr_ok = self._atr_ok(latest)
        h1_direction, h1_details = self._h1_trend_direction(df)
        details.update(h1_details)
        macd_expanding = self._macd_expanding(df)

        buy_required = {
            "上昇トレンド(EMA)": latest["ema_fast"] > latest["ema_slow"],
            "上位足(H1)が上昇方向": h1_direction in (None, "BUY"),
            "押し目からの回復": self._pullback_ok(df, "BUY"),
            "RSI帯域内(BUY)": config.RSI_BUY_MIN <= latest["rsi"] <= config.RSI_BUY_MAX,
            "スプレッド許容内": spread_ok,
            "ATR最低値以上": atr_ok,
            "MACDヒストグラムが方向一致": latest["macd_hist"] > 0,
            "MACDヒストグラムが拡大方向": macd_expanding == "BUY",
        }
        sell_required = {
            "下降トレンド(EMA)": latest["ema_fast"] < latest["ema_slow"],
            "上位足(H1)が下降方向": h1_direction in (None, "SELL"),
            "戻りからの回復": self._pullback_ok(df, "SELL"),
            "RSI帯域内(SELL)": config.RSI_SELL_MIN <= latest["rsi"] <= config.RSI_SELL_MAX,
            "スプレッド許容内": spread_ok,
            "ATR最低値以上": atr_ok,
            "MACDヒストグラムが方向一致": latest["macd_hist"] < 0,
            "MACDヒストグラムが拡大方向": macd_expanding == "SELL",
        }

        if config.REQUIRE_NO_NEW_EXTREME_5BARS:
            no_new_low, no_new_high = self._no_new_extreme_5bars(df)
            buy_required["直近5本の安値を更新せず"] = no_new_low
            sell_required["直近5本の高値を更新せず"] = no_new_high

        buy_score, buy_bonus_reasons = self._bonus_score(df, "BUY", h1_details)
        sell_score, sell_bonus_reasons = self._bonus_score(df, "SELL", h1_details)

        buy_ok = all(buy_required.values())
        sell_ok = all(sell_required.values())
        required_score = config.REQUIRED_SCORE

        buy_confidence = round((sum(buy_required.values()) / len(buy_required)) * 50 + (buy_score / _BONUS_CONDITION_COUNT) * 50)
        sell_confidence = round((sum(sell_required.values()) / len(sell_required)) * 50 + (sell_score / _BONUS_CONDITION_COUNT) * 50)

        if buy_ok and buy_score >= required_score:
            reason = f"必須条件を全て満たし、加点{buy_score}点({'/'.join(buy_bonus_reasons) or 'なし'})"
            details.update(
                score=buy_score, required_score=required_score, bonus_reasons=buy_bonus_reasons, failed_required=[]
            )
            return Signal("BUY", reason, details, buy_confidence)

        if sell_ok and sell_score >= required_score:
            reason = f"必須条件を全て満たし、加点{sell_score}点({'/'.join(sell_bonus_reasons) or 'なし'})"
            details.update(
                score=sell_score, required_score=required_score, bonus_reasons=sell_bonus_reasons, failed_required=[]
            )
            return Signal("SELL", reason, details, sell_confidence)

        if buy_ok or sell_ok:
            direction = "BUY" if buy_ok else "SELL"
            score = buy_score if buy_ok else sell_score
            bonus_reasons = buy_bonus_reasons if buy_ok else sell_bonus_reasons
            reason = f"必須条件は満たすが加点不足({direction}: {score}/{required_score}点)"
            details.update(
                score=score, required_score=required_score, bonus_reasons=bonus_reasons, failed_required=[]
            )
        else:
            failed_buy = [k for k, v in buy_required.items() if not v]
            failed_sell = [k for k, v in sell_required.items() if not v]
            reason = f"必須条件が未達(BUY未達: {', '.join(failed_buy) or 'なし'} / SELL未達: {', '.join(failed_sell) or 'なし'})"
            details.update(
                score=0,
                required_score=required_score,
                bonus_reasons=[],
                failed_required={"BUY": failed_buy, "SELL": failed_sell},
            )

        return Signal("WAIT", reason, details, max(buy_confidence, sell_confidence))

    def _spread_ok(self, latest: pd.Series) -> bool:
        if config.MAX_SPREAD_POINTS <= 0:
            return True
        if "spread" not in latest or pd.isna(latest["spread"]):
            return True  # スプレッドデータが無い場合はチェックしない(古いEA等)
        return float(latest["spread"]) <= config.MAX_SPREAD_POINTS

    def _atr_ok(self, latest: pd.Series) -> bool:
        if config.ATR_MIN_POINTS <= 0:
            return True
        if "atr" not in latest or pd.isna(latest["atr"]) or config.POINT_SIZE <= 0:
            return True  # ATRが計算できない場合はチェックしない
        atr_points = float(latest["atr"]) / config.POINT_SIZE
        return atr_points >= config.ATR_MIN_POINTS

    def _macd_expanding(self, df: pd.DataFrame) -> str | None:
        """MACDヒストグラムが前足よりどちら方向へ拡大しているか。

        拡大していない(前足以下/前足以上)、または前足が無い場合はNone
        (BUY/SELLどちらの必須条件も満たさない=WAIT側に倒す)。
        """
        if len(df) < 2:
            return None
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        if "macd_hist" not in df.columns or pd.isna(prev.get("macd_hist")):
            return None
        if latest["macd_hist"] > prev["macd_hist"]:
            return "BUY"
        if latest["macd_hist"] < prev["macd_hist"]:
            return "SELL"
        return None

    def _pullback_ok(self, df: pd.DataFrame, direction: str) -> bool:
        """EMA(短期)から十分離れた後、押し目/戻りが完了しているか。

        ATRが計算できない、または直近本数が足りない場合はFalse
        (判定不能をWAIT側に倒す、勝率優先の方針のため)。
        """
        latest = df.iloc[-1]
        if "atr" not in df.columns or pd.isna(latest.get("atr")) or float(latest["atr"]) <= 0:
            return False
        atr_value = float(latest["atr"])

        lookback = min(config.PULLBACK_LOOKBACK_BARS, len(df) - 1)
        if lookback <= 0:
            return False
        window = df.iloc[-(lookback + 1) : -1]
        if window.empty:
            return False

        window_dist = (window["close"] - window["ema_fast"]) / atr_value
        cur_dist = (latest["close"] - latest["ema_fast"]) / atr_value

        if direction == "BUY":
            had_extension = bool((window_dist >= config.PULLBACK_MIN_EXTENSION_ATR).any())
            pulled_back = 0.0 <= cur_dist <= config.PULLBACK_MAX_DISTANCE_ATR
        else:
            had_extension = bool((window_dist <= -config.PULLBACK_MIN_EXTENSION_ATR).any())
            pulled_back = -config.PULLBACK_MAX_DISTANCE_ATR <= cur_dist <= 0.0

        return had_extension and pulled_back

    def _h1_trend_direction(self, df: pd.DataFrame) -> tuple[str | None, dict[str, Any]]:
        """取引時間足のローソク足をH1へリサンプルし、EMA20/50の上下関係を返す。

        "time"列が無い、またはH1_MIN_BARS未満しかリサンプルできない場合は
        判定不能として(None, {})を返す(必須条件は素通し=フィルター無効化)。
        """
        if "time" not in df.columns or df["time"].isna().all():
            return None, {}
        try:
            times = pd.to_datetime(df["time"])
        except (TypeError, ValueError):
            return None, {}

        h1_close = pd.Series(df["close"].values, index=times).resample("1h").last().dropna()
        if len(h1_close) < config.H1_MIN_BARS:
            return None, {"h1_bars": int(len(h1_close))}

        h1_ema_fast = h1_close.ewm(span=config.H1_EMA_FAST_PERIOD, adjust=False).mean()
        h1_ema_slow = h1_close.ewm(span=config.H1_EMA_SLOW_PERIOD, adjust=False).mean()
        fast_now = float(h1_ema_fast.iloc[-1])
        slow_now = float(h1_ema_slow.iloc[-1])
        fast_prev = float(h1_ema_fast.iloc[-2]) if len(h1_ema_fast) >= 2 else fast_now

        if fast_now > slow_now:
            direction = "BUY"
        elif fast_now < slow_now:
            direction = "SELL"
        else:
            direction = None

        return direction, {
            "h1_ema_fast": fast_now,
            "h1_ema_slow": slow_now,
            "h1_slope_up": fast_now > fast_prev,
            "h1_bars": int(len(h1_close)),
        }

    def _no_new_extreme_5bars(self, df: pd.DataFrame) -> tuple[bool, bool]:
        """直近5本(最新を除く)の安値/高値を、最新足が更新していないか。

        データが5本に満たない場合は判定不能として両方Falseを返す(必須条件を
        満たさない=WAITへ倒す、安全側の扱い)。
        """
        if len(df) < 6:
            return False, False
        window = df.iloc[-6:-1]
        latest = df.iloc[-1]
        no_new_low = bool(latest["low"] >= window["low"].min())
        no_new_high = bool(latest["high"] <= window["high"].max())
        return no_new_low, no_new_high

    def _bonus_score(self, df: pd.DataFrame, direction: str, h1_details: dict[str, Any]) -> tuple[int, list[str]]:
        latest = df.iloc[-1]
        is_buy = direction == "BUY"
        score = 0
        reasons: list[str] = []

        if len(df) >= 2:
            prev = df.iloc[-2]
            if (is_buy and latest["ema_fast"] > prev["ema_fast"]) or (
                not is_buy and latest["ema_fast"] < prev["ema_fast"]
            ):
                score += 1
                reasons.append("EMAの傾きが方向一致")

        if "open" in latest and not pd.isna(latest["open"]):
            if (is_buy and latest["close"] > latest["open"]) or (not is_buy and latest["close"] < latest["open"]):
                score += 1
                reasons.append("直近足の実体が方向一致")

        if len(df) >= 3:
            recent = df.iloc[-3:]
            if is_buy and recent["low"].is_monotonic_increasing:
                score += 1
                reasons.append("直近3本の安値が切り上げ")
            elif not is_buy and recent["high"].is_monotonic_decreasing:
                score += 1
                reasons.append("直近3本の高値が切り下げ")

        if "rsi" in latest and not pd.isna(latest["rsi"]):
            if (is_buy and latest["rsi"] > 50.0) or (not is_buy and latest["rsi"] < 50.0):
                score += 1
                reasons.append("RSIが50を方向側に超過")

        h1_slope_up = h1_details.get("h1_slope_up")
        if h1_slope_up is not None:
            if (is_buy and h1_slope_up) or (not is_buy and not h1_slope_up):
                score += 1
                reasons.append("上位足(H1)のEMAも方向一致")

        return score, reasons


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
