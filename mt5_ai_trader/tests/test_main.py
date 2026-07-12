"""main.py の発注テスト用モード(FORCE_SIGNAL / TEST_ORDER_ONCE)の単体テスト。

MT5/EA/実ファイルシステムは使わず、resolve_force_signal() / apply_force_signal()
というピュア関数と、run_once()をフェイクのfeed/ai_engine/order_executorで検証する。
"""
from __future__ import annotations

import config
import main as main_module
from ai_engine import Signal


# --- resolve_loop_interval ---------------------------------------------------


def test_resolve_loop_interval_prefers_explicit_cli_value(monkeypatch):
    monkeypatch.setattr(config, "LOOP_INTERVAL_SECONDS", 60)

    assert main_module.resolve_loop_interval(15) == 15


def test_resolve_loop_interval_falls_back_to_config_when_cli_omitted(monkeypatch):
    monkeypatch.setattr(config, "LOOP_INTERVAL_SECONDS", 45)

    assert main_module.resolve_loop_interval(None) == 45


def test_resolve_loop_interval_reflects_config_json_style_change(monkeypatch):
    """config.LOOP_INTERVAL_SECONDSが実行中に変わった場合(Dashboard経由を模す)、
    --interval未指定なら次回呼び出しで新しい値がすぐ反映されることを確認する。
    """
    monkeypatch.setattr(config, "LOOP_INTERVAL_SECONDS", 60)
    assert main_module.resolve_loop_interval(None) == 60

    monkeypatch.setattr(config, "LOOP_INTERVAL_SECONDS", 10)
    assert main_module.resolve_loop_interval(None) == 10


# --- resolve_force_signal ---------------------------------------------------


def test_resolve_force_signal_empty_is_disabled():
    assert main_module.resolve_force_signal("") == ""


def test_resolve_force_signal_accepts_buy_sell_wait():
    assert main_module.resolve_force_signal("BUY") == "BUY"
    assert main_module.resolve_force_signal("SELL") == "SELL"
    assert main_module.resolve_force_signal("WAIT") == "WAIT"


def test_resolve_force_signal_rejects_invalid_value():
    assert main_module.resolve_force_signal("HOLD") == ""


# --- apply_force_signal ------------------------------------------------------


def test_apply_force_signal_noop_when_force_signal_empty(monkeypatch):
    monkeypatch.setattr(config, "DEMO_ONLY", True)
    original = Signal("WAIT", "no trend", {"rsi": 50})

    result = main_module.apply_force_signal(original, "")

    assert result is original


def test_apply_force_signal_noop_when_demo_only_false(monkeypatch):
    monkeypatch.setattr(config, "DEMO_ONLY", False)
    original = Signal("WAIT", "no trend", {"rsi": 50})

    result = main_module.apply_force_signal(original, "BUY")

    assert result is original  # DEMO_ONLY=falseならFORCE_SIGNALは無視される


def test_apply_force_signal_overrides_action_when_demo_only_true(monkeypatch):
    monkeypatch.setattr(config, "DEMO_ONLY", True)
    original = Signal("WAIT", "trend条件が揃っていません", {"rsi": 50})

    result = main_module.apply_force_signal(original, "BUY")

    assert result.action == "BUY"
    assert "[TEST MODE]" in result.reason
    assert "FORCE_SIGNAL=BUY" in result.reason
    assert result.details == original.details  # 指標の値はそのまま保持される


def test_apply_force_signal_can_force_wait_even_if_ai_said_buy(monkeypatch):
    monkeypatch.setattr(config, "DEMO_ONLY", True)
    original = Signal("BUY", "上昇トレンド", {})

    result = main_module.apply_force_signal(original, "WAIT")

    assert result.action == "WAIT"


# --- run_once integration (fakes, no real MT5/EA) ---------------------------


class _FakeFeed:
    def __init__(self):
        self.calls = 0

    def read_snapshot(self, symbol, timeframe):
        import pandas as pd

        self.calls += 1
        closes = [150.0 + i * 0.01 for i in range(30)]
        df = pd.DataFrame({"close": closes})

        class _Tick:
            bid = closes[-1]
            ask = closes[-1] + 0.003

        class _Snapshot:
            tick = _Tick()
            candles = df

        return _Snapshot()


class _FakeAiEngine:
    def decide(self, df):
        return Signal("WAIT", "トレンド・モメンタムの条件が揃っていません", {})


class _RecordingOrderExecutor:
    def __init__(self):
        self.calls: list[tuple[Signal, str | None]] = []

    def submit_if_needed(self, signal, request_id=None):
        self.calls.append((signal, request_id))
        return None


def test_run_once_uses_force_signal_and_forwards_request_id(monkeypatch):
    monkeypatch.setattr(config, "DEMO_ONLY", True)
    feed = _FakeFeed()
    ai_engine = _FakeAiEngine()
    order_executor = _RecordingOrderExecutor()

    signal = main_module.run_once(feed, ai_engine, order_executor, force_signal="BUY", request_id="test-req-1")

    assert signal is not None
    assert signal.action == "BUY"
    assert len(order_executor.calls) == 1
    submitted_signal, submitted_request_id = order_executor.calls[0]
    assert submitted_signal.action == "BUY"
    assert submitted_request_id == "test-req-1"


def test_run_once_without_force_signal_keeps_normal_ai_decision(monkeypatch):
    monkeypatch.setattr(config, "DEMO_ONLY", True)
    feed = _FakeFeed()
    ai_engine = _FakeAiEngine()
    order_executor = _RecordingOrderExecutor()

    signal = main_module.run_once(feed, ai_engine, order_executor)

    assert signal is not None
    assert signal.action == "WAIT"  # 通常運転: FakeAiEngineの判断がそのまま使われる
    # WAITなのでorder_executorへは渡るが、submit_if_needed内部でBUY/SELL以外は無視される
    assert order_executor.calls[0][0].action == "WAIT"


def test_run_once_skips_when_bot_run_state_stopped(monkeypatch):
    monkeypatch.setattr(config, "BOT_RUN_STATE", "STOPPED")
    feed = _FakeFeed()
    ai_engine = _FakeAiEngine()
    order_executor = _RecordingOrderExecutor()

    signal = main_module.run_once(feed, ai_engine, order_executor)

    assert signal is not None
    assert signal.action == "WAIT"
    assert feed.calls == 0  # 価格取得すら行わない
    assert order_executor.calls == []  # submit_if_needed自体呼ばれない


def test_run_once_skips_when_bot_run_state_emergency_stopped(monkeypatch):
    monkeypatch.setattr(config, "BOT_RUN_STATE", "EMERGENCY_STOPPED")
    feed = _FakeFeed()
    ai_engine = _FakeAiEngine()
    order_executor = _RecordingOrderExecutor()

    signal = main_module.run_once(feed, ai_engine, order_executor)

    assert signal is not None
    assert signal.action == "WAIT"
    assert "緊急停止中" in signal.reason
    assert feed.calls == 0
    assert order_executor.calls == []


def test_run_once_checks_daily_summary_every_cycle_regardless_of_bot_run_state(monkeypatch):
    """BOT_RUN_STATEがRUNNINGでなくても、日次サマリー送信チェックは毎サイクル行う。"""
    import daily_summary

    calls = []
    monkeypatch.setattr(daily_summary, "maybe_send_daily_summary", lambda feed: calls.append(feed))
    monkeypatch.setattr(config, "BOT_RUN_STATE", "STOPPED")

    feed = _FakeFeed()
    ai_engine = _FakeAiEngine()
    order_executor = _RecordingOrderExecutor()

    main_module.run_once(feed, ai_engine, order_executor)

    assert len(calls) == 1


def test_run_once_daily_summary_error_does_not_break_cycle(monkeypatch):
    import daily_summary

    def _raise(feed):
        raise RuntimeError("boom")

    monkeypatch.setattr(daily_summary, "maybe_send_daily_summary", _raise)
    monkeypatch.setattr(config, "DEMO_ONLY", True)

    feed = _FakeFeed()
    ai_engine = _FakeAiEngine()
    order_executor = _RecordingOrderExecutor()

    signal = main_module.run_once(feed, ai_engine, order_executor)

    assert signal is not None  # 通常のサイクルはそのまま続行する


def test_run_once_reloads_config_json_at_start(monkeypatch):
    """Dashboardからのconfig.json変更をサイクルの先頭で拾えることを確認する。"""
    calls = []
    monkeypatch.setattr(config, "load_config_json", lambda **kwargs: calls.append(kwargs) or True)

    feed = _FakeFeed()
    ai_engine = _FakeAiEngine()
    order_executor = _RecordingOrderExecutor()

    main_module.run_once(feed, ai_engine, order_executor)

    assert len(calls) == 1
