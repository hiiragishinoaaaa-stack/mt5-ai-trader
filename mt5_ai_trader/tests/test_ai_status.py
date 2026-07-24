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
    monkeypatch.setattr(config, "AI_DECISION_LOG_PATH", tmp_path / "ai_decisions.jsonl")
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


# --- append_decision_log ------------------------------------------------------


def test_append_decision_log_writes_one_json_line_with_score_breakdown():
    details = {
        "required_score": 7,
        "buy_score": 9,
        "buy_total": 10,
        "buy_failed": ["MACDヒストグラムが拡大方向"],
        "sell_score": 1,
        "sell_total": 10,
        "sell_failed": ["下降トレンド(EMA)"],
        "adx": 28.5,
        "regime": "TRENDING",
    }
    signal = Signal("BUY", "スコア9/10点で必要点数(7)に到達", details, confidence=90)

    ai_status.append_decision_log(signal, "USDJPY", "M15")

    file_path = config.decision_log_file_path("USDJPY")
    lines = file_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["symbol"] == "USDJPY"
    assert row["timeframe"] == "M15"
    assert row["action"] == "BUY"
    assert row["required_score"] == 7
    assert row["buy_score"] == 9
    assert row["buy_total"] == 10
    assert row["buy_failed"] == ["MACDヒストグラムが拡大方向"]
    assert row["sell_score"] == 1
    assert row["adx"] == 28.5
    assert row["regime"] == "TRENDING"
    assert "timestamp" in row


def test_append_decision_log_appends_across_multiple_calls():
    signal1 = Signal("WAIT", "1回目", {"required_score": 7, "buy_score": 3, "buy_total": 10}, confidence=0)
    signal2 = Signal("SELL", "2回目", {"required_score": 7, "sell_score": 8, "sell_total": 10}, confidence=80)

    ai_status.append_decision_log(signal1, "USDJPY", "M15")
    ai_status.append_decision_log(signal2, "USDJPY", "M15")

    lines = config.decision_log_file_path("USDJPY").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["action"] == "WAIT"
    assert json.loads(lines[1])["action"] == "SELL"


def test_append_decision_log_missing_details_keys_become_null():
    """RuleBasedAIEngine以外(LLM系エンジン等)はdetailsにスコア関連キーが
    無いため、該当フィールドはnullとして記録される(エラーにはならない)。
    """
    signal = Signal("BUY", "LLMの判断理由", {}, confidence=70)

    ai_status.append_decision_log(signal, "USDJPY", "M15")

    row = json.loads(config.decision_log_file_path("USDJPY").read_text(encoding="utf-8").splitlines()[0])
    assert row["required_score"] is None
    assert row["buy_score"] is None


def test_append_decision_log_non_primary_symbol_uses_separate_file(monkeypatch):
    monkeypatch.setattr(config, "SYMBOL", "USDJPY")
    signal = Signal("WAIT", "テスト", {}, confidence=0)

    ai_status.append_decision_log(signal, "EURUSD", "M15")

    assert config.decision_log_file_path("EURUSD") != config.AI_DECISION_LOG_PATH
    assert not config.AI_DECISION_LOG_PATH.exists()
    assert config.decision_log_file_path("EURUSD").exists()
