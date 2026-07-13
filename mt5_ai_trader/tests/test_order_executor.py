"""order_executor.py の単体テスト。MT5/EA/実ファイルシステムのMT5パス不要。

config.ORDER_REQUEST_FILE_PATH / ORDER_RESULT_FILE_PATH を一時ファイルに
差し替え、EAが結果ファイルを書き出す様子をシミュレートしてテストする。
"""
from __future__ import annotations

import json
import time

import pytest

import config
import order_executor
from ai_engine import Signal


@pytest.fixture(autouse=True)
def _patch_order_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ORDER_REQUEST_FILE_PATH", tmp_path / "artemis_order_request.json")
    monkeypatch.setattr(config, "ORDER_RESULT_FILE_PATH", tmp_path / "artemis_order_result.json")
    monkeypatch.setattr(config, "ENABLE_ORDERS", True)
    monkeypatch.setattr(config, "DEMO_ONLY", True)
    monkeypatch.setattr(config, "BOT_RUN_STATE", "RUNNING")
    monkeypatch.setattr(config, "ORDER_VOLUME", 0.01)
    monkeypatch.setattr(config, "SL_POINTS", 200)
    monkeypatch.setattr(config, "TP_POINTS", 400)
    monkeypatch.setattr(config, "MAX_CONCURRENT_POSITIONS", 3)
    monkeypatch.setattr(config, "ORDER_RESULT_WAIT_SECONDS", 2.0)
    monkeypatch.setattr(order_executor, "_RESULT_POLL_INTERVAL_SECONDS", 0.05)


def _read_request() -> dict:
    return json.loads(config.ORDER_REQUEST_FILE_PATH.read_text(encoding="utf-8"))


def _write_fake_ea_result(request_id: str, success: bool, message: str = "ok", ticket: int = 12345, retcode: int = 10009) -> None:
    payload = {
        "request_id": request_id,
        "processed_at": time.time(),
        "success": success,
        "retcode": retcode,
        "ticket": ticket,
        "message": message,
    }
    config.ORDER_RESULT_FILE_PATH.write_text(json.dumps(payload), encoding="utf-8")


def test_wait_signal_does_not_write_request():
    executor = order_executor.FileOrderExecutor()
    result = executor.submit_if_needed(Signal("WAIT", "no trend", {}), config.SYMBOL)

    assert result is None
    assert not config.ORDER_REQUEST_FILE_PATH.exists()


def test_demo_only_false_does_not_write_request(monkeypatch):
    monkeypatch.setattr(config, "DEMO_ONLY", False)
    executor = order_executor.FileOrderExecutor()

    result = executor.submit_if_needed(Signal("BUY", "uptrend", {}), config.SYMBOL)

    assert result is None
    assert not config.ORDER_REQUEST_FILE_PATH.exists()


def test_enable_orders_false_does_not_write_request(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_ORDERS", False)
    executor = order_executor.FileOrderExecutor()

    result = executor.submit_if_needed(Signal("BUY", "uptrend", {}), config.SYMBOL)

    assert result is None
    assert not config.ORDER_REQUEST_FILE_PATH.exists()


@pytest.mark.parametrize("bot_run_state", ["STOPPED", "EMERGENCY_STOPPED"])
def test_bot_run_state_not_running_does_not_write_request(monkeypatch, bot_run_state):
    monkeypatch.setattr(config, "BOT_RUN_STATE", bot_run_state)
    executor = order_executor.FileOrderExecutor()

    result = executor.submit_if_needed(Signal("BUY", "uptrend", {}), config.SYMBOL)

    assert result is None
    assert not config.ORDER_REQUEST_FILE_PATH.exists()


def test_buy_signal_writes_request_with_expected_fields():
    executor = order_executor.FileOrderExecutor()

    import threading

    def fake_ea():
        # requestファイルが書かれるまで少し待ってから結果を返す(EAの動作を模す)
        for _ in range(50):
            if config.ORDER_REQUEST_FILE_PATH.exists():
                break
            time.sleep(0.02)
        request = _read_request()
        _write_fake_ea_result(request["request_id"], success=True)

    t = threading.Thread(target=fake_ea)
    t.start()
    result = executor.submit_if_needed(Signal("BUY", "uptrend", {}), config.SYMBOL)
    t.join()

    request = _read_request()
    assert request["action"] == "BUY"
    assert request["symbol"] == config.SYMBOL
    assert request["volume"] == 0.01
    assert request["sl_points"] == 200
    assert request["tp_points"] == 400
    assert request["max_positions"] == 3
    assert request["demo_only"] is True

    assert result is not None
    assert result.success is True
    assert result.ticket == 12345


def test_sell_signal_failure_result_is_reported():
    executor = order_executor.FileOrderExecutor()

    import threading

    def fake_ea():
        for _ in range(50):
            if config.ORDER_REQUEST_FILE_PATH.exists():
                break
            time.sleep(0.02)
        request = _read_request()
        _write_fake_ea_result(request["request_id"], success=False, message="rejected: position already exists")

    t = threading.Thread(target=fake_ea)
    t.start()
    result = executor.submit_if_needed(Signal("SELL", "downtrend", {}), config.SYMBOL)
    t.join()

    assert result is not None
    assert result.success is False
    assert "already exists" in result.message


def test_no_result_file_times_out_gracefully(monkeypatch):
    monkeypatch.setattr(config, "ORDER_RESULT_WAIT_SECONDS", 0.2)
    executor = order_executor.FileOrderExecutor()

    result = executor.submit_if_needed(Signal("BUY", "uptrend", {}), config.SYMBOL)

    assert result is None
    assert config.ORDER_REQUEST_FILE_PATH.exists()  # リクエスト自体は書き出されている


def test_explicit_request_id_is_used_in_request_file():
    executor = order_executor.FileOrderExecutor()

    import threading

    def fake_ea():
        for _ in range(50):
            if config.ORDER_REQUEST_FILE_PATH.exists():
                break
            time.sleep(0.02)
        request = _read_request()
        _write_fake_ea_result(request["request_id"], success=True)

    t = threading.Thread(target=fake_ea)
    t.start()
    result = executor.submit_if_needed(Signal("BUY", "uptrend", {}), config.SYMBOL, request_id="fixed-test-id-1")
    t.join()

    assert _read_request()["request_id"] == "fixed-test-id-1"
    assert result is not None
    assert result.success is True


def test_same_request_id_is_not_submitted_twice(monkeypatch):
    """発注テスト用モード(TEST_ORDER_ONCE)向け: 同じrequest_idでの再送出をブロックする。"""
    executor = order_executor.FileOrderExecutor()

    write_calls: list[dict] = []
    monkeypatch.setattr(executor, "_write_request", lambda req, symbol: write_calls.append(req))
    monkeypatch.setattr(
        executor,
        "_wait_for_result",
        lambda request_id, symbol: order_executor.OrderResult(success=True, message="ok", ticket=1, retcode=10009),
    )

    first = executor.submit_if_needed(Signal("BUY", "uptrend", {}), config.SYMBOL, request_id="dup-id")
    second = executor.submit_if_needed(Signal("BUY", "uptrend", {}), config.SYMBOL, request_id="dup-id")

    assert first is not None
    assert first.success is True
    assert second is None  # 二重発注防止によりスキップされる
    assert len(write_calls) == 1  # リクエストファイルへの書き出しは1回だけ


def test_omitted_request_id_generates_unique_ids_each_call(monkeypatch):
    """request_idを省略した通常運転では、毎回新しいIDで送出できる(既存動作を維持)。"""
    executor = order_executor.FileOrderExecutor()

    write_calls: list[dict] = []
    monkeypatch.setattr(executor, "_write_request", lambda req, symbol: write_calls.append(req))
    monkeypatch.setattr(
        executor,
        "_wait_for_result",
        lambda request_id, symbol: order_executor.OrderResult(success=True, message="ok"),
    )

    first = executor.submit_if_needed(Signal("BUY", "uptrend", {}), config.SYMBOL)
    second = executor.submit_if_needed(Signal("BUY", "uptrend", {}), config.SYMBOL)

    assert first is not None and second is not None
    assert len(write_calls) == 2
    assert write_calls[0]["request_id"] != write_calls[1]["request_id"]
