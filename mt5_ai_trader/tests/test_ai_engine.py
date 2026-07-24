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
    get_shadow_engine,
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
    # balancedプリセット相当(統一スコア方式、満点は条件数に応じて約9〜13点)。
    monkeypatch.setattr(config, "REQUIRED_SCORE", 7)
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
    """必須条件(押し目待ち・MACD方向一致を含む)を満たし、加点条件も
    (H1データなしのため最大5/6点で)フルに満たすBUY用の5本セット。

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
    # H1データ(time列)が無いためH1関連の2条件はスコア対象外。全条件を
    # 満たす完璧なセットアップのため満点(10/10)になる。
    assert signal.details["score"] == 10


def test_decide_returns_sell_on_bearish_setup():
    df = pd.DataFrame(_bearish_setup_rows())
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "SELL"
    assert signal.details["score"] == 10


def test_decide_always_includes_both_direction_score_breakdown_on_buy():
    """2026-07、Fable5との相談を踏まえた変更: 実際に発動した方向(BUY)
    だけでなく、発動しなかった方向(SELL)のスコア内訳もdetailsに残る
    (ai_status.append_decision_logでの閾値バックテスト分析用)。
    """
    df = pd.DataFrame(_bullish_setup_rows())
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "BUY"
    assert signal.details["buy_score"] == 10
    assert signal.details["buy_total"] == 10
    assert signal.details["buy_failed"] == []
    assert signal.details["sell_score"] is not None
    assert signal.details["sell_total"] is not None
    assert isinstance(signal.details["sell_failed"], list)
    assert signal.details["required_score"] == config.REQUIRED_SCORE


def test_decide_always_includes_both_direction_score_breakdown_on_wait():
    df = pd.DataFrame([_row(ema_fast=151.0, ema_slow=150.0, macd_hist=-0.5, rsi=90.0)])
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "WAIT"
    assert signal.details["buy_score"] == 3
    assert signal.details["sell_score"] == 3
    assert signal.details["buy_total"] == 8
    assert signal.details["sell_total"] == 8


def test_decide_returns_wait_when_score_far_below_threshold():
    """上昇トレンドだがRSIが帯域外(SELL方向の判断材料が混在)で、BUY/SELL
    どちらの方向も合計スコアがREQUIRED_SCORE(7)に遠く届かないケース。
    """
    df = pd.DataFrame([_row(ema_fast=151.0, ema_slow=150.0, macd_hist=-0.5, rsi=90.0)])
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "WAIT"
    assert signal.details["score"] == 3  # BUY: トレンド・ATR・RSI>50の3点のみ
    assert "必要点数(7)未達" in signal.reason


def test_decide_returns_wait_when_score_insufficient():
    """トレンド・RSI帯域・MACD方向一致等は満たすが、EMAの傾き・陽線実体・
    3本安値切り上げ・MACD拡大の4条件が揃わず、必要スコア(7)に届かない
    ケース(_bullish_setup_rows()の最新足だけ差し替え、10点満点中6点)。
    """
    rows = _bullish_setup_rows()
    rows[-1] = _row(
        open=150.0,
        close=149.5,  # 陰線(陽線一致の条件を落とす)
        high=150.1,
        low=149.0,  # 前足(149.2)より安い=3本安値切り上げが崩れる
        ema_fast=149.5,  # 前足(idx3)と同値=傾き横ばい(条件を落とす)
        ema_slow=148.0,
        macd_hist=0.15,  # 前足(0.2)より縮小=方向一致は満たすがMACD拡大は落ちる
        rsi=58.0,
    )
    df = pd.DataFrame(rows)
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "WAIT"
    assert signal.details["score"] == 6
    assert signal.details["score"] < signal.details["required_score"]
    assert "必要点数(7)未達" in signal.reason


def test_decide_returns_wait_on_empty_dataframe():
    engine = RuleBasedAIEngine()
    signal = engine.decide(pd.DataFrame())
    assert signal.action == "WAIT"


def test_decide_conservative_extra_filter_adds_condition_and_can_block(monkeypatch):
    """REQUIRE_NO_NEW_EXTREME_5BARS有効時、直近5本の安値を更新する足は
    「直近5本の安値を更新せず」条件が満点にも失敗リストにも1点追加される
    (conservativeプリセット相当)。統一スコア方式では単独で即ブロックする
    わけではなく、REQUIRED_SCOREを満点近くまで上げた場合にこの1点差が
    WAITへ倒すことを確認する(新低値を作る足は直近3本安値切り上げ条件も
    連動して失敗するため、あわせて2点減点になる)。
    """
    rows = _bullish_setup_rows()
    padding = [
        _row(low=149.6, high=150.8, close=150.0, open=150.0, ema_fast=150.2, ema_slow=150.0, rsi=55.0)
        for _ in range(3)
    ]
    df = pd.DataFrame(padding + rows)
    df.loc[df.index[-1], "low"] = 148.5  # 直近5本の最安値(149.0)を下回る

    monkeypatch.setattr(config, "REQUIRE_NO_NEW_EXTREME_5BARS", True)
    monkeypatch.setattr(config, "REQUIRED_SCORE", 10)  # 満点(11)近くまで引き上げる
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)

    assert signal.action == "WAIT"
    assert signal.details["score"] == 9
    assert "直近5本の安値を更新せず" in signal.details["failed_required"]["BUY"]


def test_decide_h1_downtrend_lowers_buy_score_without_hard_blocking(monkeypatch):
    """取引時間足(M15)は上昇トレンドで、上位足(H1)が下降トレンドの場合、
    H1関連の2条件(方向一致・EMA傾き一致)が失敗リストに入りBUYスコアが
    下がる。統一スコア方式ではこれ単独でエントリーを即ブロックはしない
    (通常のREQUIRED_SCORE(7)なら他の条件でカバーされBUYのまま)一方、
    REQUIRED_SCOREを満点近くまで上げれば、この減点がWAITへ倒す材料になる
    ことを確認する(2026-07に必須条件から通常のスコア条件へ変更。
    ai_engine.pyのdocstring参照)。
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
    # 最新足(idx16)はローカルEMA近くまで戻す(H1以外はほぼ全条件を満たす
    # ようにして、H1不一致による減点分だけを見る)。
    rows[15].update(ema_fast=148.5, macd_hist=0.2)  # dist=(149.5-148.5)/1.0=1.0 >= 0.5(拡張)
    rows[16].update(ema_fast=148.8, macd_hist=0.3, rsi=58.0)  # dist=(149.0-148.8)/1.0=0.2(押し目完了)

    df = pd.DataFrame(rows)
    df["time"] = times

    engine = RuleBasedAIEngine()
    signal_normal = engine.decide(df)
    assert signal_normal.action == "BUY"  # 通常の必要点数(7)なら他条件でカバーされる
    assert signal_normal.details.get("h1_ema_fast") is not None
    assert signal_normal.details["score"] == 9

    monkeypatch.setattr(config, "REQUIRED_SCORE", 10)
    signal_strict = engine.decide(df)
    assert signal_strict.action == "WAIT"
    assert "上位足(H1)が方向一致" in signal_strict.details["failed_required"]["BUY"]
    assert "上位足(H1)のEMAも方向一致" in signal_strict.details["failed_required"]["BUY"]


def test_decide_missing_pullback_lowers_score_without_hard_blocking():
    """EMAから十分離れたままで戻ってきていない(押し目が完了していない)
    場合、「押し目からの回復」条件が1点減点される。統一スコア方式では
    これ単独ではブロックしない(通常のREQUIRED_SCORE(7)ならBUYのまま)が、
    REQUIRED_SCOREを満点近くまで上げればWAITへ倒す材料になる。
    """
    rows = _bullish_setup_rows()
    # 最新足を、押し目が完了する前(EMAからまだ離れたまま)に変更する。
    rows[-1] = _row(
        open=150.0, close=150.5, high=150.6, low=149.9,
        ema_fast=149.7, ema_slow=148.0, macd_hist=0.3, rsi=58.0,
    )  # dist=(150.5-149.7)/1.0=0.8 > PULLBACK_MAX_DISTANCE_ATR(0.3)
    df = pd.DataFrame(rows)
    engine = RuleBasedAIEngine()

    signal_normal = engine.decide(df)
    assert signal_normal.action == "BUY"
    assert signal_normal.details["score"] == 9

    config.REQUIRED_SCORE = 10
    try:
        signal_strict = engine.decide(df)
    finally:
        config.REQUIRED_SCORE = 7
    assert signal_strict.action == "WAIT"
    assert "押し目からの回復" in signal_strict.details["failed_required"]["BUY"]


def test_decide_regime_is_diagnostic_only_by_default():
    """REQUIRE_TRENDING_REGIME=false(既定)なら、ADXがどんな値でもスコアに
    影響しない(details['regime']は表示されるが、条件としては加算されない)。
    """
    rows = _bullish_setup_rows()
    df = pd.DataFrame(rows)
    df["adx"] = 5.0  # 明確なレンジ相場
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "BUY"
    assert signal.details["score"] == 10  # レジーム条件は未加算のまま満点
    assert signal.details["regime"] == "RANGING"


def test_decide_require_trending_regime_adds_scored_condition(monkeypatch):
    """REQUIRE_TRENDING_REGIME=true時、ADX>=ADX_TREND_THRESHOLDならBUY/SELL
    共通で1点加算され、未満なら満点が1点増えたうえでその1点を落とす。
    """
    monkeypatch.setattr(config, "REQUIRE_TRENDING_REGIME", True)
    monkeypatch.setattr(config, "ADX_TREND_THRESHOLD", 25.0)
    rows = _bullish_setup_rows()

    df_trending = pd.DataFrame(rows)
    df_trending["adx"] = 30.0
    engine = RuleBasedAIEngine()
    signal_trending = engine.decide(df_trending)
    assert signal_trending.action == "BUY"
    assert signal_trending.details["score"] == 11
    assert signal_trending.details["regime"] == "TRENDING"

    df_ranging = pd.DataFrame(rows)
    df_ranging["adx"] = 10.0
    signal_ranging = engine.decide(df_ranging)
    assert signal_ranging.action == "BUY"  # 1点減っても他条件でカバーされる
    assert signal_ranging.details["score"] == 10
    assert signal_ranging.details["regime"] == "RANGING"


def test_decide_require_trending_regime_without_adx_is_skipped(monkeypatch):
    """ADX列が無い(high/lowが未提供等)場合、REQUIRE_TRENDING_REGIME=true
    でもレジーム条件はスコア対象外になる(判定不能をペナルティにしない)。
    """
    monkeypatch.setattr(config, "REQUIRE_TRENDING_REGIME", True)
    rows = _bullish_setup_rows()
    df = pd.DataFrame(rows)  # adx列なし
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "BUY"
    assert signal.details["score"] == 10
    assert signal.details.get("regime") is None


def test_decide_scores_but_does_not_block_when_macd_not_expanding():
    """MACDヒストグラムの拡大(勢いの加速)は他条件と同様の1点条件であり、
    方向自体さえ合っていれば拡大していなくてもエントリーはブロックされない
    (拡大時より1点減るだけ)。
    """
    rows = _bullish_setup_rows()
    # 最新足のMACDヒストグラムを前足(0.2)より縮小させる(方向=+のままなので
    # 「MACDヒストグラムが方向一致」条件は満たす)。
    rows[-1] = _row(
        open=149.6, close=149.85, high=149.95, low=149.4,
        ema_fast=149.7, ema_slow=148.0, macd_hist=0.15, rsi=58.0,
    )
    df = pd.DataFrame(rows)
    engine = RuleBasedAIEngine()
    signal = engine.decide(df)
    assert signal.action == "BUY"
    assert signal.details["score"] == 9  # フル10点からMACD拡大分(-1)


def test_get_ai_engine_returns_rule_based_by_default():
    engine = get_ai_engine("rule_based")
    assert isinstance(engine, RuleBasedAIEngine)


def test_get_ai_engine_unimplemented_raises_on_decide():
    engine = get_ai_engine("mistral")
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


def test_get_ai_engine_returns_gemini_engine_wrapped_in_throttle():
    from gemini_engine import GeminiEngine

    engine = get_ai_engine("gemini")
    assert isinstance(engine, CandleThrottledEngine)
    assert isinstance(engine._inner, GeminiEngine)


# --- get_shadow_engine (GEMINI_SHADOW) ---------------------------------------


def test_get_shadow_engine_returns_none_by_default(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_SHADOW", False)
    assert get_shadow_engine() is None


def test_get_shadow_engine_returns_gemini_engine_wrapped_in_throttle_when_enabled(monkeypatch):
    from gemini_engine import GeminiEngine

    monkeypatch.setattr(config, "GEMINI_SHADOW", True)
    engine = get_shadow_engine()
    assert isinstance(engine, CandleThrottledEngine)
    assert isinstance(engine._inner, GeminiEngine)


def test_get_shadow_engine_uses_gemini_even_when_ai_engine_is_rule_based(monkeypatch):
    """AI_ENGINE(実際の発注判断)がrule_based(既定)のままでも、シャドー
    判断は常にGeminiで行う(config.GEMINI_SHADOWはAI_ENGINEと独立)。
    """
    monkeypatch.setattr(config, "AI_ENGINE", "rule_based")
    monkeypatch.setattr(config, "GEMINI_SHADOW", True)
    from gemini_engine import GeminiEngine

    engine = get_shadow_engine()
    assert isinstance(engine, CandleThrottledEngine)
    assert isinstance(engine._inner, GeminiEngine)


# --- evaluate_conditions (バックテスト条件別監査用) --------------------------


def test_evaluate_conditions_returns_label_bool_pairs_matching_score():
    """evaluate_conditions()が返す(ラベル, 成否)のリストは、decide()内部の
    採点(score/total)と完全に一致する(同じ_build_conditionsを共有)。
    """
    df = pd.DataFrame(_bullish_setup_rows())
    engine = RuleBasedAIEngine()

    conditions = engine.evaluate_conditions(df, "BUY")
    signal = engine.decide(df)

    assert all(isinstance(label, str) and isinstance(ok, bool) for label, ok in conditions)
    score = sum(1 for _, ok in conditions if ok)
    assert score == signal.details["buy_score"]
    assert len(conditions) == signal.details["buy_total"]


def test_evaluate_conditions_buy_and_sell_same_length():
    df = pd.DataFrame(_bullish_setup_rows())
    engine = RuleBasedAIEngine()
    assert len(engine.evaluate_conditions(df, "BUY")) == len(engine.evaluate_conditions(df, "SELL"))


def test_evaluate_conditions_empty_when_indicators_missing():
    engine = RuleBasedAIEngine()
    assert engine.evaluate_conditions(pd.DataFrame(), "BUY") == []
    # closeはあるがema等が無いDataFrame
    assert engine.evaluate_conditions(pd.DataFrame([{"close": 150.0}]), "BUY") == []


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
