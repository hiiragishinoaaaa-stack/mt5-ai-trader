"""ai_engine.py の単体テスト。MT5への接続なしで実行できる。"""
from __future__ import annotations

import pandas as pd

import pytest

from ai_engine import (
    CandleThrottledEngine,
    RuleBasedAIEngine,
    Signal,
    describe_market_conditions,
    get_ai_engine,
    parse_llm_signal_json,
)


def _row(**overrides) -> dict:
    base = {
        "close": 150.0,
        "ema_fast": 150.0,
        "ema_slow": 150.0,
        "rsi": 50.0,
        "macd": 0.0,
        "macd_signal": 0.0,
        "macd_hist": 0.0,
    }
    base.update(overrides)
    return base


def test_decide_returns_buy_on_bullish_setup():
    df = pd.DataFrame([_row(ema_fast=151.0, ema_slow=150.0, macd_hist=0.5, rsi=55.0)])
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "BUY"
    assert signal.confidence == 100  # 3条件すべて満たす場合のみBUYが成立するため


def test_decide_returns_sell_on_bearish_setup():
    df = pd.DataFrame([_row(ema_fast=149.0, ema_slow=150.0, macd_hist=-0.5, rsi=45.0)])
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "SELL"


def test_decide_returns_wait_when_signals_conflict():
    df = pd.DataFrame([_row(ema_fast=151.0, ema_slow=150.0, macd_hist=-0.5, rsi=55.0)])
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "WAIT"
    assert 0 < signal.confidence < 100  # 一部の条件(上昇トレンド)だけ満たしている


def test_decide_returns_wait_on_empty_dataframe():
    engine = RuleBasedAIEngine()
    signal = engine.decide(pd.DataFrame())
    assert signal.action == "WAIT"


def test_get_ai_engine_returns_rule_based_by_default():
    engine = get_ai_engine("rule_based")
    assert isinstance(engine, RuleBasedAIEngine)


def test_get_ai_engine_unimplemented_raises_on_decide():
    engine = get_ai_engine("gemini")
    try:
        engine.decide(pd.DataFrame())
        assert False, "NotImplementedErrorが送出されるべき"
    except NotImplementedError:
        pass


def test_get_ai_engine_returns_openai_engine_wrapped_in_throttle():
    from openai_engine import OpenAIEngine

    engine = get_ai_engine("openai")
    assert isinstance(engine, CandleThrottledEngine)
    assert isinstance(engine._inner, OpenAIEngine)


def test_get_ai_engine_returns_claude_engine_wrapped_in_throttle():
    from claude_engine import ClaudeEngine

    engine = get_ai_engine("claude")
    assert isinstance(engine, CandleThrottledEngine)
    assert isinstance(engine._inner, ClaudeEngine)


# --- describe_market_conditions ---------------------------------------------


def test_describe_market_conditions_includes_symbol_and_indicators():
    df = pd.DataFrame([_row(close=151.234, rsi=61.2)])
    text = describe_market_conditions(df, "USDJPY", "M15")

    assert "USDJPY" in text
    assert "M15" in text
    assert "151.234" in text
    assert "61.2" in text


# --- parse_llm_signal_json ---------------------------------------------------


def test_parse_llm_signal_json_parses_clean_json():
    signal = parse_llm_signal_json('{"action": "BUY", "reason": "上昇トレンド", "confidence": 80}')

    assert signal.action == "BUY"
    assert signal.reason == "上昇トレンド"
    assert signal.confidence == 80.0


def test_parse_llm_signal_json_extracts_json_from_surrounding_text():
    signal = parse_llm_signal_json('以下が判断結果です:\n{"action": "WAIT", "reason": "様子見", "confidence": 10}\nよろしくお願いします')

    assert signal.action == "WAIT"
    assert signal.confidence == 10.0


def test_parse_llm_signal_json_clamps_confidence_to_0_100():
    signal = parse_llm_signal_json('{"action": "SELL", "reason": "test", "confidence": 999}')

    assert signal.confidence == 100.0


def test_parse_llm_signal_json_rejects_invalid_action():
    with pytest.raises(ValueError):
        parse_llm_signal_json('{"action": "HOLD", "reason": "test", "confidence": 50}')


def test_parse_llm_signal_json_rejects_non_json_text():
    with pytest.raises(ValueError):
        parse_llm_signal_json("すみません、判断できません")


def test_parse_llm_signal_json_rejects_malformed_json():
    with pytest.raises(ValueError):
        parse_llm_signal_json('{"action": "BUY", "reason": }')


# --- CandleThrottledEngine ----------------------------------------------------


class _CountingEngine:
    """decide()が呼ばれた回数を記録するだけのフェイクエンジン(API課金相当)。"""

    def __init__(self):
        self.calls = 0

    def decide(self, df: pd.DataFrame) -> Signal:
        self.calls += 1
        return Signal("BUY", f"call #{self.calls}", {}, 90.0)


def _candle_row(time: int, **overrides) -> dict:
    row = _row(**overrides)
    row["time"] = time
    return row


def test_candle_throttled_engine_calls_inner_once_per_new_candle():
    inner = _CountingEngine()
    engine = CandleThrottledEngine(inner)

    df_candle_1 = pd.DataFrame([_candle_row(1000)])
    s1 = engine.decide(df_candle_1)
    s2 = engine.decide(df_candle_1)  # 同じローソク足のまま再度呼ばれる(main.pyの次サイクル相当)

    assert inner.calls == 1  # 2回目はキャッシュを再利用し、内部エンジンは呼ばれない
    assert s1.action == "BUY"
    assert s2.action == "BUY"
    assert "再利用" in s2.reason


def test_candle_throttled_engine_calls_inner_again_on_new_candle():
    inner = _CountingEngine()
    engine = CandleThrottledEngine(inner)

    engine.decide(pd.DataFrame([_candle_row(1000)]))
    engine.decide(pd.DataFrame([_candle_row(1000)]))
    engine.decide(pd.DataFrame([_candle_row(1900)]))  # 新しいローソク足(例: 15分後)

    assert inner.calls == 2


def test_candle_throttled_engine_calls_inner_on_empty_dataframe():
    inner = _CountingEngine()
    engine = CandleThrottledEngine(inner)

    signal = engine.decide(pd.DataFrame())

    assert inner.calls == 1
    assert signal.action == "BUY"
