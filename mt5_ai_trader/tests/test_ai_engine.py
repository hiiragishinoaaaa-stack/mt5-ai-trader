"""ai_engine.py の単体テスト。MT5への接続なしで実行できる。"""
from __future__ import annotations

import pandas as pd

import pytest

import config
from ai_engine import (
    CandleThrottledEngine,
    RuleBasedAIEngine,
    Signal,
    describe_market_conditions,
    get_ai_engine,
    parse_llm_signal_json,
)


@pytest.fixture(autouse=True)
def _patch_scoring_config(monkeypatch):
    """RuleBasedAIEngineのスコアリング設定をテスト間で決定的にする
    (ENTRY_STRICTNESSプリセットの既定値変更に依存しないようにするため)。
    """
    monkeypatch.setattr(config, "RSI_BUY_MIN", 50.0)
    monkeypatch.setattr(config, "RSI_BUY_MAX", 65.0)
    monkeypatch.setattr(config, "RSI_SELL_MIN", 35.0)
    monkeypatch.setattr(config, "RSI_SELL_MAX", 50.0)
    monkeypatch.setattr(config, "REQUIRED_SCORE", 3)
    monkeypatch.setattr(config, "REQUIRE_NO_NEW_EXTREME_5BARS", False)
    monkeypatch.setattr(config, "MAX_SPREAD_POINTS", 30.0)
    monkeypatch.setattr(config, "ATR_MIN_POINTS", 0.0)
    monkeypatch.setattr(config, "POINT_SIZE", 0.001)
    # 押し目/戻り待ちの必須条件(勝率優先ロジック)。テストのローソク足本数を
    # 少なく保てるよう、既定値より小さいlookbackにする。
    monkeypatch.setattr(config, "PULLBACK_LOOKBACK_BARS", 3)
    monkeypatch.setattr(config, "PULLBACK_MIN_EXTENSION_ATR", 0.5)
    monkeypatch.setattr(config, "PULLBACK_MAX_DISTANCE_ATR", 0.3)


def _row(**overrides) -> dict:
    base = {
        "open": 150.0,
        "close": 150.0,
        "high": 150.0,
        "low": 150.0,
        "ema_fast": 150.0,
        "ema_slow": 150.0,
        "rsi": 50.0,
        "macd_hist": 0.0,
        "spread": 10.0,
        "atr": 1.0,
    }
    base.update(overrides)
    return base


def _bullish_setup_rows() -> list[dict]:
    """必須条件(押し目待ち・MACD方向+拡大を含む)を満たし、加点条件も
    (H1データなしのため最大4/5点で)フルに満たすBUY用の5本セット。

    idx0: 基準。idx1-3: 押し目判定のlookbackウィンドウ(idx1でEMAから
    十分上に離れる=押し目の起点)。idx4: 最新足(EMA近くまで押し目が
    完了し、EMAの傾き・陽線・安値切り上げ・RSI>50の加点条件も揃う)。
    """
    return [
        _row(open=148.7, close=148.8, high=148.9, low=148.6, ema_fast=148.8, ema_slow=148.0, macd_hist=-0.1, rsi=50.0),
        _row(open=149.0, close=150.0, high=150.1, low=148.9, ema_fast=149.0, ema_slow=148.0, macd_hist=0.1, rsi=55.0),
        _row(open=150.0, close=149.6, high=150.1, low=149.0, ema_fast=149.3, ema_slow=148.0, macd_hist=0.15, rsi=54.0),
        _row(open=149.6, close=149.7, high=149.8, low=149.2, ema_fast=149.5, ema_slow=148.0, macd_hist=0.2, rsi=56.0),
        _row(open=149.6, close=149.85, high=149.95, low=149.4, ema_fast=149.7, ema_slow=148.0, macd_hist=0.3, rsi=58.0),
    ]


def _bearish_setup_rows() -> list[dict]:
    """_bullish_setup_rows()のSELL版(値・向きを左右対称にしたもの)。"""
    return [
        _row(open=151.3, close=151.2, high=151.4, low=151.1, ema_fast=151.2, ema_slow=152.0, macd_hist=0.1, rsi=50.0),
        _row(open=151.0, close=150.0, high=151.1, low=149.9, ema_fast=151.0, ema_slow=152.0, macd_hist=-0.1, rsi=45.0),
        _row(open=150.0, close=150.4, high=151.0, low=149.9, ema_fast=150.7, ema_slow=152.0, macd_hist=-0.15, rsi=46.0),
        _row(open=150.4, close=150.3, high=150.8, low=150.2, ema_fast=150.5, ema_slow=152.0, macd_hist=-0.2, rsi=44.0),
        _row(open=150.4, close=150.15, high=150.6, low=150.05, ema_fast=150.3, ema_slow=152.0, macd_hist=-0.3, rsi=42.0),
    ]


def test_decide_returns_buy_on_bullish_setup():
    df = pd.DataFrame(_bullish_setup_rows())
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "BUY"
    # H1データ(time列)が無いためH1加点は付かず、4/5点が上限。
    assert signal.details["score"] == 4


def test_decide_returns_sell_on_bearish_setup():
    df = pd.DataFrame(_bearish_setup_rows())
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "SELL"
    assert signal.details["score"] == 4


def test_decide_returns_wait_when_required_conditions_not_met():
    """上昇トレンドだがRSIが帯域外(SELL方向の判断材料が混在)なため必須条件が未達。"""
    df = pd.DataFrame([_row(ema_fast=151.0, ema_slow=150.0, macd_hist=-0.5, rsi=90.0)])
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "WAIT"
    assert "必須条件が未達" in signal.reason


def test_decide_returns_wait_when_required_met_but_score_insufficient():
    """必須条件(トレンド・H1・押し目・RSI・MACD方向+拡大)は満たすが、
    加点条件(EMAの傾き・陽線)が揃わないため必要スコアに届かないケース。

    _bullish_setup_rows()の最新足だけ、EMAの傾きを横ばい・実体を陰線に
    変える(押し目・MACD等の必須条件はそのまま満たす)。加点は
    RSI>50・3本安値切り上げの2点のみ(必要スコア3点に届かない)。
    """
    rows = _bullish_setup_rows()
    rows[-1] = _row(
        open=150.0,
        close=149.65,
        high=150.1,
        low=149.3,
        ema_fast=149.5,  # 前足(idx3)と同値=傾き横ばい(EMA傾き加点なし)
        ema_slow=148.0,
        macd_hist=0.25,  # 前足(0.2)より拡大=必須条件は満たす
        rsi=58.0,
    )
    df = pd.DataFrame(rows)
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "WAIT"
    assert "加点不足" in signal.reason
    assert signal.details["score"] < signal.details["required_score"]


def test_decide_returns_wait_on_empty_dataframe():
    engine = RuleBasedAIEngine()
    signal = engine.decide(pd.DataFrame())
    assert signal.action == "WAIT"


def test_decide_conservative_extra_filter_blocks_new_low(monkeypatch):
    """REQUIRE_NO_NEW_EXTREME_5BARS有効時、直近5本の安値を更新するとBUYが
    ブロックされる(conservativeプリセット相当)。
    """
    rows = _bullish_setup_rows()
    padding = [
        _row(low=149.6, high=150.8, close=150.0, open=150.0, ema_fast=150.2, ema_slow=150.0, rsi=55.0)
        for _ in range(3)
    ]
    df = pd.DataFrame(padding + rows)
    df.loc[df.index[-1], "low"] = 148.5  # 直近5本の最安値(149.0)を下回る

    monkeypatch.setattr(config, "REQUIRE_NO_NEW_EXTREME_5BARS", True)
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)

    assert signal.action == "WAIT"


def test_decide_blocks_buy_against_h1_downtrend(monkeypatch):
    """取引時間足(M15)は上昇トレンドでも、上位足(H1)が下降トレンドの場合は
    BUYが必須条件の時点でブロックされる(勝率優先ロジック②)。
    """
    monkeypatch.setattr(config, "H1_MIN_BARS", 3)

    times = pd.date_range("2026-01-01 00:00", periods=17, freq="15min")
    # 1時間ごとの終値を151.0→149.0へ下降させる(H1のEMA20<EMA50=下降と
    # 判定されるように、resample('1h').last()で拾われる各バケット末尾の
    # 値だけを厳密に制御する)。
    hourly_close = [151.0, 150.5, 150.0, 149.5, 149.0]
    rows = []
    for i, _t in enumerate(times):
        bucket = min(i // 4, 4)
        rows.append(_row(close=hourly_close[bucket], ema_fast=148.8, ema_slow=148.0, rsi=50.0, macd_hist=0.0))
    # バケット境界(resampleが実際に拾う行)の終値を明示的に固定する。
    for idx, bucket in ((3, 0), (7, 1), (11, 2), (15, 3), (16, 4)):
        rows[idx]["close"] = hourly_close[bucket]

    # 直近の押し目ウィンドウ(idx13-15)のどこかでEMAから十分離れておき、
    # 最新足(idx16)はローカルEMA近くまで戻す(H1以外の必須条件は全て
    # 満たすようにして、H1フィルターだけが原因でブロックされることを
    # 確認する)。
    rows[15].update(ema_fast=148.5, macd_hist=0.2)  # dist=(149.5-148.5)/1.0=1.0 >= 0.5(拡張)
    rows[16].update(ema_fast=148.8, macd_hist=0.3, rsi=58.0)  # dist=(149.0-148.8)/1.0=0.2(押し目完了)

    df = pd.DataFrame(rows)
    df["time"] = times

    engine = RuleBasedAIEngine()
    signal = engine.decide(df)

    assert signal.action == "WAIT"
    assert signal.details.get("h1_ema_fast") is not None
    assert "上位足(H1)が上昇方向" in signal.details["failed_required"]["BUY"]


def test_decide_blocks_entry_without_pullback():
    """EMAから十分離れたままで戻ってきていない(押し目が完了していない)
    場合、トレンド・RSI・MACDが揃っていてもBUYは必須条件で弾かれる。
    """
    rows = _bullish_setup_rows()
    # 最新足を、押し目が完了する前(EMAからまだ離れたまま)に変更する。
    rows[-1] = _row(
        open=150.0, close=150.5, high=150.6, low=149.9,
        ema_fast=149.7, ema_slow=148.0, macd_hist=0.3, rsi=58.0,
    )  # dist=(150.5-149.7)/1.0=0.8 > PULLBACK_MAX_DISTANCE_ATR(0.3)
    df = pd.DataFrame(rows)
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "WAIT"
    assert "押し目からの回復" in signal.details["failed_required"]["BUY"]


def test_decide_blocks_entry_when_macd_histogram_not_expanding():
    """MACDヒストグラムが方向自体は合っていても縮小中(勢い喪失)の場合、
    他の必須条件が揃っていてもBUYは弾かれる。
    """
    rows = _bullish_setup_rows()
    # 最新足のMACDヒストグラムを前足(0.2)より縮小させる。
    rows[-1] = _row(
        open=149.6, close=149.85, high=149.95, low=149.4,
        ema_fast=149.7, ema_slow=148.0, macd_hist=0.1, rsi=58.0,
    )
    df = pd.DataFrame(rows)
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "WAIT"
    assert "MACDヒストグラムが拡大方向" in signal.details["failed_required"]["BUY"]


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
