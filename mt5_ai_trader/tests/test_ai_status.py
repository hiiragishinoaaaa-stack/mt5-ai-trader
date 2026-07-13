"""ai_status.py の単体テスト。MT5/EA不要。"""
from __future__ import annotations

import json
import time

import pytest

import ai_status
import config
from ai_engine import Signal


@pytest.fixture(autouse=True)
def _patch_ai_status_path(tmp_path, monkeypatch):
    file_path = tmp_path / "artemis_ai_status.json"
    monkeypatch.setattr(config, "AI_STATUS_FILE_PATH", file_path)
    return file_path


def test_write_then_read_round_trip():
    signal = Signal("BUY", "テスト理由", {}, confidence=100)
    ai_status.write_status(signal, "USDJPY", "M15")

    snapshot = ai_status.read_status("USDJPY")

    assert snapshot.action == "BUY"
    assert snapshot.confidence == 100
    assert snapshot.reason == "テスト理由"
    assert snapshot.symbol == "USDJPY"
    assert snapshot.timeframe == "M15"


def test_write_then_read_round_trip_non_primary_symbol(monkeypatch, tmp_path):
    """複数銘柄対応(Phase 12): プライマリ以外の銘柄は別ファイルへ書き出す。"""
    monkeypatch.setattr(config, "SYMBOL", "USDJPY")
    signal = Signal("SELL", "テスト理由2", {}, confidence=80)
    ai_status.write_status(signal, "EURUSD", "M15")

    snapshot = ai_status.read_status("EURUSD")

    assert snapshot.symbol == "EURUSD"
    assert snapshot.action == "SELL"
    # プライマリ銘柄のファイルとは別ファイルに書かれている
    assert config.ai_status_file_path("EURUSD") != config.AI_STATUS_FILE_PATH
    assert not config.AI_STATUS_FILE_PATH.exists()


def test_read_status_missing_file_raises():
    with pytest.raises(ai_status.AiStatusError, match="見つかりません"):
        ai_status.read_status("USDJPY")


def test_read_status_stale_data_raises():
    file_path = config.AI_STATUS_FILE_PATH
    payload = {
        "action": "WAIT",
        "confidence": 0,
        "reason": "古いデータ",
        "symbol": "USDJPY",
        "timeframe": "M15",
        "updated_at": time.time() - 999,
    }
    file_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ai_status.AiStatusError, match="古すぎます"):
        ai_status.read_status("USDJPY", max_staleness_seconds=30)


def test_read_status_corrupted_json_raises():
    config.AI_STATUS_FILE_PATH.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ai_status.AiStatusError):
        ai_status.read_status("USDJPY")
