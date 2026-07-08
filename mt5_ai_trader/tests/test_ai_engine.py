"""ai_engine.py の単体テスト。MT5への接続なしで実行できる。"""
from __future__ import annotations

import pandas as pd

from ai_engine import RuleBasedAIEngine, get_ai_engine


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


def test_decide_returns_wait_on_empty_dataframe():
    engine = RuleBasedAIEngine()
    signal = engine.decide(pd.DataFrame())
    assert signal.action == "WAIT"


def test_get_ai_engine_returns_rule_based_by_default():
    engine = get_ai_engine("rule_based")
    assert isinstance(engine, RuleBasedAIEngine)


def test_get_ai_engine_unimplemented_raises_on_decide():
    engine = get_ai_engine("openai")
    try:
        engine.decide(pd.DataFrame())
        assert False, "NotImplementedErrorが送出されるべき"
    except NotImplementedError:
        pass
