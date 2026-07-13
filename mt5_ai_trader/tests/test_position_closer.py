"""position_closer.py の単体テスト。MT5/EA/実ファイルシステムのMT5パス不要。

config.CLOSE_REQUEST_FILE_PATH / CLOSE_RESULT_FILE_PATH を一時ファイルに
差し替え、EAが結果ファイルを書き出す様子をシミュレートしてテストする。
"""
from __future__ import annotations

import json
import threading
import time

import pytest

import config
import position_closer


@pytest.fixture(autouse=True)
def _patch_close_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CLOSE_REQUEST_FILE_PATH", tmp_path / "artemis_close_request.json")
    monkeypatch.setattr(config, "CLOSE_RESULT_FILE_PATH", tmp_path / "artemis_close_result.json")
    monkeypatch.setattr(config, "ENABLE_ORDERS", True)
    monkeypatch.setattr(config, "DEMO_ONLY", True)
    monkeypatch.setattr(config, "SYMBOL", "USDJPY")
    monkeypatch.setattr(config, "ORDER_RESULT_WAIT_SECONDS", 2.0)


def _read_request() -> dict:
    return json.loads(config.CLOSE_REQUEST_FILE_PATH.read_text(encoding="utf-8"))


def _write_fake_ea_result(request_id: str, success: bool, message: str = "closed 1/1 position(s)", closed_count: int = 1) -> None:
    payload = {
        "request_id": request_id,
        "processed_at": time.time(),
        "success": success,
        "closed_count": closed_count,
        "message": message,
    }
    config.CLOSE_RESULT_FILE_PATH.write_text(json.dumps(payload), encoding="utf-8")


def test_enable_orders_false_does_not_write_request(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_ORDERS", False)
    closer = position_closer.FilePositionCloser()

    result = closer.close_all()

    assert result.success is False
    assert not config.CLOSE_REQUEST_FILE_PATH.exists()


def test_demo_only_false_does_not_write_request(monkeypatch):
    monkeypatch.setattr(config, "DEMO_ONLY", False)
    closer = position_closer.FilePositionCloser()

    result = closer.close_all()

    assert result.success is False
    assert not config.CLOSE_REQUEST_FILE_PATH.exists()


def test_close_all_writes_request_with_expected_fields():
    closer = position_closer.FilePositionCloser()

    def fake_ea():
        for _ in range(50):
            if config.CLOSE_REQUEST_FILE_PATH.exists():
                break
            time.sleep(0.02)
        request = _read_request()
        _write_fake_ea_result(request["request_id"], success=True)

    t = threading.Thread(target=fake_ea)
    t.start()
    result = closer.close_all()
    t.join()

    request = _read_request()
    assert request["symbol"] == "USDJPY"
    assert request["demo_only"] is True
    assert result.success is True
    assert result.closed_count == 1


def test_close_all_reports_failure_from_ea():
    closer = position_closer.FilePositionCloser()

    def fake_ea():
        for _ in range(50):
            if config.CLOSE_REQUEST_FILE_PATH.exists():
                break
            time.sleep(0.02)
        request = _read_request()
        _write_fake_ea_result(request["request_id"], success=False, message="rejected: symbol mismatch", closed_count=0)

    t = threading.Thread(target=fake_ea)
    t.start()
    result = closer.close_all()
    t.join()

    assert result.success is False
    assert "rejected" in result.message


def test_close_all_no_result_file_times_out_gracefully(monkeypatch):
    monkeypatch.setattr(config, "ORDER_RESULT_WAIT_SECONDS", 0.2)
    closer = position_closer.FilePositionCloser()

    result = closer.close_all()

    assert result.success is False
    assert "タイムアウト" in result.message
