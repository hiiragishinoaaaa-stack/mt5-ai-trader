"""main.py の発注テスト用モード(FORCE_SIGNAL / TEST_ORDER_ONCE)の単体テスト。

MT5/EA/実ファイルシステムは使わず、resolve_force_signal() / apply_force_signal()
というピュア関数と、run_once()をフェイクのfeed/ai_engine/order_executorで検証する。
"""
from __future__ import annotations

import json

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
        self.calls: list[tuple[Signal, str, str | None]] = []

    def submit_if_needed(self, signal, symbol, atr_price=None, request_id=None):
        self.calls.append((signal, symbol, request_id))
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
    submitted_signal, submitted_symbol, submitted_request_id = order_executor.calls[0]
    assert submitted_signal.action == "BUY"
    assert submitted_symbol == config.SYMBOL
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


def test_run_once_checks_close_notifier_every_cycle_regardless_of_bot_run_state(monkeypatch):
    """BOT_RUN_STATEがRUNNINGでなくても、決済通知チェックは毎サイクル行う。"""
    import close_notifier

    calls = []
    monkeypatch.setattr(close_notifier, "notify_newly_closed_trades", lambda feed: calls.append(feed))
    monkeypatch.setattr(config, "BOT_RUN_STATE", "STOPPED")

    feed = _FakeFeed()
    ai_engine = _FakeAiEngine()
    order_executor = _RecordingOrderExecutor()

    main_module.run_once(feed, ai_engine, order_executor)

    assert len(calls) == 1


def test_run_once_close_notifier_error_does_not_break_cycle(monkeypatch):
    import close_notifier

    def _raise(feed):
        raise RuntimeError("boom")

    monkeypatch.setattr(close_notifier, "notify_newly_closed_trades", _raise)
    monkeypatch.setattr(config, "DEMO_ONLY", True)

    feed = _FakeFeed()
    ai_engine = _FakeAiEngine()
    order_executor = _RecordingOrderExecutor()

    signal = main_module.run_once(feed, ai_engine, order_executor)

    assert signal is not None  # 通常のサイクルはそのまま続行する


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


def test_run_once_writes_ea_config_every_cycle_regardless_of_bot_run_state(monkeypatch):
    """BOT_RUN_STATEがRUNNINGでなくても、EA向けTIMEFRAME反映は毎サイクル行う
    (PCなしでDashboardのTIMEFRAME変更をEAへ伝えるため、停止中でも同期は続ける)。
    """
    import ea_config_writer

    calls = []
    monkeypatch.setattr(ea_config_writer, "write_ea_config", lambda tf, symbol: calls.append((tf, symbol)))
    monkeypatch.setattr(config, "TIMEFRAME", "M1")
    monkeypatch.setattr(config, "BOT_RUN_STATE", "STOPPED")

    feed = _FakeFeed()
    ai_engine = _FakeAiEngine()
    order_executor = _RecordingOrderExecutor()

    main_module.run_once(feed, ai_engine, order_executor)

    assert calls == [("M1", config.SYMBOL)]


def test_run_once_ea_config_write_error_does_not_break_cycle(monkeypatch):
    import ea_config_writer

    def _raise(timeframe, symbol):
        raise OSError("boom")

    monkeypatch.setattr(ea_config_writer, "write_ea_config", _raise)
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


# --- risk_manager連携 ---------------------------------------------------------


class _BuySignalAiEngine:
    def decide(self, df):
        return Signal("BUY", "テスト用の強制BUY", {})


def test_run_once_blocks_order_when_risk_manager_denies(monkeypatch):
    """risk_managerがエントリーを許可しない場合、BUY/SELLはWAITへ差し替えられ、
    order_executorへは送出されない。
    """
    import risk_manager

    monkeypatch.setattr(config, "DEMO_ONLY", True)
    monkeypatch.setattr(
        risk_manager,
        "check_entry_allowed",
        lambda symbol, history_feed, account_feed, **kwargs: risk_manager.RiskCheckResult(
            False, "クールダウン中です(テスト)"
        ),
    )

    feed = _FakeFeed()
    ai_engine = _BuySignalAiEngine()
    order_executor = _RecordingOrderExecutor()

    signal = main_module.run_once(feed, ai_engine, order_executor)

    assert signal is not None
    assert signal.action == "WAIT"
    assert "クールダウン中です(テスト)" in signal.reason
    assert order_executor.calls[0][0].action == "WAIT"  # BUYはWAITに差し替えられて渡される


def test_run_once_submits_order_when_risk_manager_allows(monkeypatch):
    import risk_manager

    monkeypatch.setattr(config, "DEMO_ONLY", True)
    monkeypatch.setattr(
        risk_manager,
        "check_entry_allowed",
        lambda symbol, history_feed, account_feed, **kwargs: risk_manager.RiskCheckResult(True),
    )

    feed = _FakeFeed()
    ai_engine = _BuySignalAiEngine()
    order_executor = _RecordingOrderExecutor()

    signal = main_module.run_once(feed, ai_engine, order_executor)

    assert signal is not None
    assert signal.action == "BUY"
    assert order_executor.calls[0][0].action == "BUY"


def test_run_once_does_not_call_risk_manager_for_wait_signal(monkeypatch):
    """WAIT判断の場合、risk_managerは呼ばれない(不要なファイル読み込みを避ける)。"""
    import risk_manager

    calls = []
    monkeypatch.setattr(
        risk_manager,
        "check_entry_allowed",
        lambda symbol, history_feed, account_feed, **kwargs: calls.append(symbol)
        or risk_manager.RiskCheckResult(True),
    )

    feed = _FakeFeed()
    ai_engine = _FakeAiEngine()  # 常にWAIT
    order_executor = _RecordingOrderExecutor()

    main_module.run_once(feed, ai_engine, order_executor)

    assert calls == []


# --- ATRベースのSL/TP連携 -----------------------------------------------------


class _FakeFeedWithAtr:
    """high/low列を含む(=ATRが計算できる)価格データを返すフェイクfeed。"""

    def read_snapshot(self, symbol, timeframe):
        import pandas as pd

        n = 30
        closes = [150.0 + i * 0.01 for i in range(n)]
        df = pd.DataFrame(
            {
                "close": closes,
                "high": [c + 0.05 for c in closes],
                "low": [c - 0.05 for c in closes],
            }
        )

        class _Tick:
            bid = closes[-1]
            ask = closes[-1] + 0.003

        class _Snapshot:
            tick = _Tick()
            candles = df

        return _Snapshot()


class _AtrRecordingOrderExecutor:
    def __init__(self):
        self.calls: list[tuple[Signal, str, float | None]] = []

    def submit_if_needed(self, signal, symbol, atr_price=None, request_id=None):
        self.calls.append((signal, symbol, atr_price))
        return None


def test_run_once_passes_computed_atr_to_order_executor(monkeypatch):
    monkeypatch.setattr(config, "DEMO_ONLY", True)

    feed = _FakeFeedWithAtr()
    ai_engine = _BuySignalAiEngine()
    order_executor = _AtrRecordingOrderExecutor()

    main_module.run_once(feed, ai_engine, order_executor)

    assert len(order_executor.calls) == 1
    _, _, atr_price = order_executor.calls[0]
    assert atr_price is not None
    assert atr_price > 0


def test_run_once_atr_price_is_none_when_high_low_unavailable(monkeypatch):
    """high/low列が無い(ATRが計算できない)フィードでは、atr_price=Noneのまま
    渡される(order_executor側でfixedモードにフォールバックする)。
    """
    monkeypatch.setattr(config, "DEMO_ONLY", True)

    feed = _FakeFeed()  # close列のみ
    ai_engine = _BuySignalAiEngine()
    order_executor = _AtrRecordingOrderExecutor()

    main_module.run_once(feed, ai_engine, order_executor)

    assert len(order_executor.calls) == 1
    _, _, atr_price = order_executor.calls[0]
    assert atr_price is None


# --- Geminiシャドーモード(GEMINI_SHADOW) -------------------------------------


class _FakeShadowEngine:
    def __init__(self, signal=None, error=False):
        self.calls = 0
        self._signal = signal or Signal("SELL", "シャドーの判断理由", {}, confidence=75)
        self._error = error

    def decide(self, df):
        self.calls += 1
        if self._error:
            raise RuntimeError("shadow engine boom")
        return self._signal


def _patch_ai_status_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "AI_STATUS_FILE_PATH", tmp_path / "artemis_ai_status.json")
    monkeypatch.setattr(config, "AI_DECISION_LOG_PATH", tmp_path / "ai_decisions.jsonl")
    monkeypatch.setattr(config, "AI_SHADOW_LOG_PATH", tmp_path / "ai_shadow_log.jsonl")


def test_run_once_records_shadow_signal_without_affecting_order(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DEMO_ONLY", True)
    _patch_ai_status_paths(monkeypatch, tmp_path)
    feed = _FakeFeed()
    ai_engine = _FakeAiEngine()  # 常にWAIT
    order_executor = _RecordingOrderExecutor()
    shadow_engine = _FakeShadowEngine(Signal("SELL", "シャドーの判断理由", {}, confidence=75))

    signal = main_module.run_once(feed, ai_engine, order_executor, shadow_engine=shadow_engine)

    assert signal is not None
    assert signal.action == "WAIT"  # 実際の発注判断はルールベースのまま変わらない
    assert shadow_engine.calls == 1
    assert order_executor.calls[0][0].action == "WAIT"  # 発注にはシャドー判断を使わない

    shadow_log_path = config.shadow_log_file_path(config.SYMBOL)
    lines = shadow_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["rule_action"] == "WAIT"
    assert row["gemini_action"] == "SELL"
    assert row["agree"] is False

    status_payload = json.loads(config.ai_status_file_path(config.SYMBOL).read_text(encoding="utf-8"))
    assert status_payload["action"] == "WAIT"
    assert status_payload["gemini_shadow"]["action"] == "SELL"
    assert status_payload["gemini_shadow"]["confidence"] == 75


def test_run_once_without_shadow_engine_writes_no_shadow_log(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DEMO_ONLY", True)
    _patch_ai_status_paths(monkeypatch, tmp_path)
    feed = _FakeFeed()
    ai_engine = _FakeAiEngine()
    order_executor = _RecordingOrderExecutor()

    main_module.run_once(feed, ai_engine, order_executor)  # shadow_engine省略(既定None)

    assert not config.shadow_log_file_path(config.SYMBOL).exists()
    status_payload = json.loads(config.ai_status_file_path(config.SYMBOL).read_text(encoding="utf-8"))
    assert status_payload["gemini_shadow"] is None


def test_run_once_shadow_engine_error_does_not_break_main_flow(monkeypatch, tmp_path):
    """シャドーエンジンが例外を投げても、本来のAI判断・発注は通常通り行われる
    (記録のみに影響、という設計。_run_symbol_cycleのdocstring参照)。
    """
    monkeypatch.setattr(config, "DEMO_ONLY", True)
    _patch_ai_status_paths(monkeypatch, tmp_path)
    feed = _FakeFeed()
    ai_engine = _BuySignalAiEngine()
    order_executor = _RecordingOrderExecutor()
    shadow_engine = _FakeShadowEngine(error=True)

    signal = main_module.run_once(feed, ai_engine, order_executor, shadow_engine=shadow_engine)

    assert signal is not None
    assert signal.action == "BUY"
    assert len(order_executor.calls) == 1
    assert order_executor.calls[0][0].action == "BUY"
    assert not config.shadow_log_file_path(config.SYMBOL).exists()
