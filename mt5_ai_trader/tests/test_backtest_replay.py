"""backtest_replay.py の単体テスト。MT5/EA不要、合成データのみで実行できる。"""
from __future__ import annotations

import json

import pandas as pd
import pytest

import backtest_replay as replay
import config
from ai_engine import Signal
from backtest_replay import BarScore, ReplayResult, _decide_action, simulate


def _bar(index: int, minute: int, buy_score: int, sell_score: int, high: float, low: float, close: float) -> BarScore:
    details = {
        "close": close,
        "high": high,
        "low": low,
        "buy_score": buy_score,
        "sell_score": sell_score,
    }
    action = "BUY" if buy_score >= sell_score and buy_score > 0 else "WAIT"
    signal = Signal(action, "テスト", details, confidence=50)
    return BarScore(index=index, time=pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=minute), signal=signal)


# --- _decide_action -----------------------------------------------------------


def test_decide_action_buy_when_only_buy_qualifies():
    bar = _bar(0, 0, buy_score=8, sell_score=2, high=100, low=99, close=99.5)
    assert _decide_action(bar, required_score=7) == "BUY"


def test_decide_action_sell_when_only_sell_qualifies():
    bar = _bar(0, 0, buy_score=2, sell_score=8, high=100, low=99, close=99.5)
    assert _decide_action(bar, required_score=7) == "SELL"


def test_decide_action_wait_when_neither_qualifies():
    bar = _bar(0, 0, buy_score=3, sell_score=3, high=100, low=99, close=99.5)
    assert _decide_action(bar, required_score=7) == "WAIT"


def test_decide_action_prefers_buy_on_tie():
    bar = _bar(0, 0, buy_score=8, sell_score=8, high=100, low=99, close=99.5)
    assert _decide_action(bar, required_score=7) == "BUY"


def test_decide_action_sell_wins_when_higher_than_buy():
    bar = _bar(0, 0, buy_score=7, sell_score=9, high=100, low=99, close=99.5)
    assert _decide_action(bar, required_score=7) == "SELL"


# --- simulate: エントリー・決済 ------------------------------------------------


def test_simulate_take_profit_closes_long():
    bars = [
        _bar(0, 0, buy_score=8, sell_score=0, high=100.0, low=100.0, close=100.0),  # エントリー
        _bar(1, 15, buy_score=0, sell_score=0, high=104.1, low=99.9, close=102.0),  # TP到達(+400pt)
    ]
    result = simulate(bars, required_score=7, sl_points=200, tp_points=400, point_size=0.01)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.direction == "BUY"
    assert trade.reason == "take_profit"
    assert trade.pnl_points == pytest.approx(400.0)


def test_simulate_stop_loss_closes_long():
    bars = [
        _bar(0, 0, buy_score=8, sell_score=0, high=100.0, low=100.0, close=100.0),
        _bar(1, 15, buy_score=0, sell_score=0, high=100.1, low=97.9, close=98.0),  # SL到達(-200pt)
    ]
    result = simulate(bars, required_score=7, sl_points=200, tp_points=400, point_size=0.01)

    trade = result.trades[0]
    assert trade.reason == "stop_loss"
    assert trade.pnl_points == pytest.approx(-200.0)


def test_simulate_short_direction_mirrors_long():
    bars = [
        _bar(0, 0, buy_score=0, sell_score=8, high=100.0, low=100.0, close=100.0),  # SELLエントリー
        _bar(1, 15, buy_score=0, sell_score=0, high=100.1, low=95.9, close=96.0),  # 値下がりでTP到達
    ]
    result = simulate(bars, required_score=7, sl_points=200, tp_points=400, point_size=0.01)

    trade = result.trades[0]
    assert trade.direction == "SELL"
    assert trade.reason == "take_profit"
    assert trade.pnl_points == pytest.approx(400.0)


def test_simulate_same_bar_sl_and_tp_prefers_stop_loss_by_default():
    """同じバーでSL/TP両方に触れた場合、既定(optimistic_fill=False)では
    保守的にSLを優先する。"""
    bars = [
        _bar(0, 0, buy_score=8, sell_score=0, high=100.0, low=100.0, close=100.0),
        _bar(1, 15, buy_score=0, sell_score=0, high=104.1, low=97.9, close=99.0),  # 同じバーでTP/SL両方到達
    ]
    result = simulate(bars, required_score=7, sl_points=200, tp_points=400, point_size=0.01)

    assert result.trades[0].reason == "stop_loss"


def test_simulate_same_bar_sl_and_tp_optimistic_fill_prefers_take_profit():
    bars = [
        _bar(0, 0, buy_score=8, sell_score=0, high=100.0, low=100.0, close=100.0),
        _bar(1, 15, buy_score=0, sell_score=0, high=104.1, low=97.9, close=99.0),
    ]
    result = simulate(
        bars, required_score=7, sl_points=200, tp_points=400, point_size=0.01, optimistic_fill=True
    )

    assert result.trades[0].reason == "take_profit"


def test_simulate_no_new_entry_while_position_open():
    bars = [
        _bar(0, 0, buy_score=8, sell_score=0, high=100.0, low=100.0, close=100.0),
        _bar(1, 15, buy_score=8, sell_score=0, high=100.5, low=99.5, close=100.2),  # 未決済のまま、新規は開かない
        _bar(2, 30, buy_score=0, sell_score=0, high=104.1, low=99.9, close=102.0),  # TP到達
    ]
    result = simulate(bars, required_score=7, sl_points=200, tp_points=400, point_size=0.01)

    assert len(result.trades) == 1  # 2本目では新規エントリーしていない


def test_simulate_entry_bars_own_high_low_not_checked_for_that_trade():
    """エントリーしたその足自身の高値/安値では、そのトレードのSL/TP判定を
    行わない(未来の値動きだけを見る、というより「その足の終値でエントリー
    した後」を模した設計。エントリー足のhigh/lowが極端でも同じ足では
    決済しない)。
    """
    bars = [
        _bar(0, 0, buy_score=8, sell_score=0, high=999.0, low=1.0, close=100.0),  # 同じ足でSL/TP相当を含むが無視される
    ]
    result = simulate(bars, required_score=7, sl_points=200, tp_points=400, point_size=0.01)

    assert len(result.trades) == 1
    assert result.trades[0].reason == "still_open"


def test_simulate_unqualified_scores_open_no_trade():
    bars = [_bar(0, 0, buy_score=3, sell_score=3, high=100.0, low=100.0, close=100.0)]
    result = simulate(bars, required_score=7, sl_points=200, tp_points=400, point_size=0.01)
    assert result.trades == []


# --- ReplayResult ---------------------------------------------------------------


def test_replay_result_stats():
    result = ReplayResult(required_score=7)
    result.trades = [
        ReplayTradeStub(pnl_points=400.0, reason="take_profit"),
        ReplayTradeStub(pnl_points=-200.0, reason="stop_loss"),
        ReplayTradeStub(pnl_points=400.0, reason="take_profit"),
        ReplayTradeStub(pnl_points=0.0, reason="still_open"),
    ]

    assert result.still_open_count == 1
    assert len(result.closed_trades) == 3
    assert result.win_rate == pytest.approx(2 / 3 * 100)
    assert result.expectancy_points == pytest.approx((400 - 200 + 400) / 3)
    assert result.total_pnl_points == pytest.approx(600.0)


def ReplayTradeStub(pnl_points: float, reason: str):
    from backtest_replay import ReplayTrade

    return ReplayTrade(
        direction="BUY",
        entry_index=0,
        entry_time=pd.Timestamp("2026-01-01"),
        entry_price=100.0,
        pnl_points=pnl_points,
        reason=reason,
    )


def test_replay_result_max_drawdown():
    result = ReplayResult(required_score=7)
    result.trades = [
        ReplayTradeStub(pnl_points=100.0, reason="take_profit"),  # 累積+100(ピーク)
        ReplayTradeStub(pnl_points=-300.0, reason="stop_loss"),  # 累積-200(ピークからの下落幅-300)
        ReplayTradeStub(pnl_points=50.0, reason="take_profit"),  # 累積-150(最大DDは更新しない)
    ]

    assert result.max_drawdown_points == pytest.approx(-300.0)


def test_replay_result_empty_trades_is_safe():
    result = ReplayResult(required_score=7)
    assert result.win_rate == 0.0
    assert result.expectancy_points == 0.0
    assert result.total_pnl_points == 0.0
    assert result.max_drawdown_points == 0.0
    assert result.still_open_count == 0


# --- load_candles ---------------------------------------------------------------


def test_load_candles_parses_export_json_and_sorts_by_time(tmp_path):
    payload = {
        "symbol": "USDJPY",
        "timeframe": "M15",
        "exported_at": 1700000900,
        "candles": [
            {"time": 1700000900, "open": 150.2, "high": 150.3, "low": 150.1, "close": 150.25, "spread": 2},
            {"time": 1700000000, "open": 150.0, "high": 150.1, "low": 149.9, "close": 150.05, "spread": 2},
        ],
    }
    path = tmp_path / "history.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    df = replay.load_candles(path)

    assert list(df["close"]) == [150.05, 150.25]  # 時系列順(古い順)に並び替えられている
    assert pd.api.types.is_datetime64_any_dtype(df["time"])


def test_load_candles_raises_on_empty_candles(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"symbol": "USDJPY", "timeframe": "M15", "candles": []}), encoding="utf-8")

    with pytest.raises(ValueError):
        replay.load_candles(path)


def test_infer_point_size_jpy_pair():
    candles = pd.DataFrame({"close": [163.8, 164.1, 162.9]})
    assert replay.infer_point_size(candles) == 0.001


def test_infer_point_size_non_jpy_pair():
    candles = pd.DataFrame({"close": [1.1368, 1.1401, 1.1290]})
    assert replay.infer_point_size(candles) == 0.00001


# --- compute_bar_scores: 本番ロジックとの結合テスト -----------------------------


def _synthetic_candles(n: int) -> pd.DataFrame:
    rows = []
    price = 150.0
    t = 1700000000
    for i in range(n):
        price += 0.01 if i % 2 == 0 else -0.005
        o = price
        c = price + 0.002
        h = max(o, c) + 0.01
        low = min(o, c) - 0.01
        rows.append({"time": t, "open": o, "high": h, "low": low, "close": c, "spread": 2})
        t += 900
        price = c
    return pd.DataFrame(rows)


def test_compute_bar_scores_matches_live_decide_for_same_window(monkeypatch):
    """本番のRuleBasedAIEngine.decide()を、同じ本数のローリングウィンドウに
    対して直接呼んだ場合と、compute_bar_scoresの最後のバーの結果が一致する
    こと(本番との整合性の回帰テスト)。
    """
    import indicators
    from ai_engine import RuleBasedAIEngine

    candles = _synthetic_candles(150)
    bars_count = 100

    bar_scores = replay.compute_bar_scores(candles, bars_count)
    assert len(bar_scores) == len(candles) - bars_count + 1

    last_window = candles.iloc[-bars_count:].reset_index(drop=True)
    enriched = indicators.add_indicators(last_window)
    expected_signal = RuleBasedAIEngine().decide(enriched)

    last_bar = bar_scores[-1]
    assert last_bar.buy_score == (expected_signal.details.get("buy_score") or 0)
    assert last_bar.sell_score == (expected_signal.details.get("sell_score") or 0)
    assert last_bar.close == pytest.approx(expected_signal.details["close"])


# --- CLI end-to-end smoke test ---------------------------------------------------


def test_main_runs_end_to_end_and_writes_decision_log(tmp_path, monkeypatch, capsys):
    candles = _synthetic_candles(150)
    payload = {
        "symbol": "USDJPY",
        "timeframe": "M15",
        "exported_at": int(candles.iloc[-1]["time"]),
        "candles": candles.to_dict(orient="records"),
    }
    candles_file = tmp_path / "history.json"
    candles_file.write_text(json.dumps(payload), encoding="utf-8")
    decision_log_out = tmp_path / "decisions.jsonl"

    monkeypatch.setattr(
        "sys.argv",
        [
            "backtest_replay.py",
            "--candles-file", str(candles_file),
            "--bars-count", "100",
            "--required-scores", "3,7,11",
            "--decision-log-out", str(decision_log_out),
        ],
    )

    replay.main()

    out = capsys.readouterr().out
    assert "閾値N" in out
    assert decision_log_out.exists()
    lines = decision_log_out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 51  # 150本 - 100(bars_count) + 1
    row = json.loads(lines[0])
    assert row["symbol"] == "USDJPY"
    assert "buy_score" in row
    assert "ema_fast" in row
