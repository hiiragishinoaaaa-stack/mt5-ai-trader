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
    monkeypatch.setattr(config, "AI_SHADOW_LOG_PATH", tmp_path / "ai_shadow_log.jsonl")
    # ローテーションは既定で大きめの上限にしておき、他のテストに影響しない
    # ようにする(ローテーション自体のテストは個別に上限を小さくする)。
    monkeypatch.setattr(config, "AI_LOG_MAX_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr(config, "AI_LOG_BACKUP_COUNT", 5)
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


def test_append_decision_log_includes_raw_indicator_values():
    """得点内訳だけでなく、生のRSI/EMA/ATR等の指標値も記録される
    (2026-07、Fable5との相談を踏まえて追加。過去ログだけでRSI帯域の
    見直し等を再採点できるようにするため)。
    """
    details = {
        "open": 150.1,
        "close": 150.3,
        "high": 150.4,
        "low": 150.0,
        "ema_fast": 150.2,
        "ema_slow": 149.8,
        "rsi": 58.2,
        "macd_hist": 0.05,
        "atr": 0.12,
        "spread": 3.0,
        "h1_ema_fast": 150.5,
        "h1_ema_slow": 150.1,
        "h1_slope_up": True,
        "h1_bars": 20,
    }
    signal = Signal("BUY", "テスト", details, confidence=80)

    ai_status.append_decision_log(signal, "USDJPY", "M15")

    row = json.loads(config.decision_log_file_path("USDJPY").read_text(encoding="utf-8").splitlines()[0])
    assert row["open"] == 150.1
    assert row["close"] == 150.3
    assert row["high"] == 150.4
    assert row["low"] == 150.0
    assert row["ema_fast"] == 150.2
    assert row["ema_slow"] == 149.8
    assert row["rsi"] == 58.2
    assert row["macd_hist"] == 0.05
    assert row["atr"] == 0.12
    assert row["spread"] == 3.0
    assert row["h1_ema_fast"] == 150.5
    assert row["h1_ema_slow"] == 150.1
    assert row["h1_slope_up"] is True
    assert row["h1_bars"] == 20


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


# --- ログローテーション(_rotate_if_needed) -----------------------------------


def test_append_decision_log_rotates_when_size_exceeds_limit(monkeypatch):
    """ファイルサイズが上限を超えていたら、既存の内容を.1.jsonlへ退避し、
    新しい行だけの新規ファイルから始める。
    """
    monkeypatch.setattr(config, "AI_LOG_MAX_BYTES", 1)  # 1バイトでも即ローテーションさせる
    monkeypatch.setattr(config, "AI_LOG_BACKUP_COUNT", 5)
    signal = Signal("WAIT", "1回目", {"required_score": 7}, confidence=0)
    ai_status.append_decision_log(signal, "USDJPY", "M15")

    file_path = config.decision_log_file_path("USDJPY")
    assert len(file_path.read_text(encoding="utf-8").splitlines()) == 1

    signal2 = Signal("BUY", "2回目", {"required_score": 7}, confidence=90)
    ai_status.append_decision_log(signal2, "USDJPY", "M15")

    archived = file_path.with_name(f"{file_path.stem}.1{file_path.suffix}")
    assert archived.exists()
    assert json.loads(archived.read_text(encoding="utf-8").splitlines()[0])["reason"] == "1回目"
    # 新しいファイルには新しい行だけが入っている(古い内容は引き継がない)。
    new_lines = file_path.read_text(encoding="utf-8").splitlines()
    assert len(new_lines) == 1
    assert json.loads(new_lines[0])["reason"] == "2回目"


def test_append_decision_log_rotation_shifts_older_generations(monkeypatch):
    monkeypatch.setattr(config, "AI_LOG_MAX_BYTES", 1)
    monkeypatch.setattr(config, "AI_LOG_BACKUP_COUNT", 2)
    file_path = config.decision_log_file_path("USDJPY")

    for i in range(3):
        ai_status.append_decision_log(Signal("WAIT", f"{i}回目", {}, confidence=0), "USDJPY", "M15")

    gen1 = file_path.with_name(f"{file_path.stem}.1{file_path.suffix}")
    gen2 = file_path.with_name(f"{file_path.stem}.2{file_path.suffix}")
    # 直近(3回目)は現行ファイル、2回目が.1、1回目が.2へ世代交代している。
    assert json.loads(file_path.read_text(encoding="utf-8").splitlines()[0])["reason"] == "2回目"
    assert json.loads(gen1.read_text(encoding="utf-8").splitlines()[0])["reason"] == "1回目"
    assert json.loads(gen2.read_text(encoding="utf-8").splitlines()[0])["reason"] == "0回目"


def test_append_decision_log_rotation_drops_oldest_beyond_backup_count(monkeypatch):
    monkeypatch.setattr(config, "AI_LOG_MAX_BYTES", 1)
    monkeypatch.setattr(config, "AI_LOG_BACKUP_COUNT", 1)
    file_path = config.decision_log_file_path("USDJPY")
    gen1 = file_path.with_name(f"{file_path.stem}.1{file_path.suffix}")

    for i in range(3):
        ai_status.append_decision_log(Signal("WAIT", f"{i}回目", {}, confidence=0), "USDJPY", "M15")

    # backup_count=1なので、.2.jsonlは作られず、.1.jsonlは常に直前の1世代のみ。
    assert not file_path.with_name(f"{file_path.stem}.2{file_path.suffix}").exists()
    assert json.loads(gen1.read_text(encoding="utf-8").splitlines()[0])["reason"] == "1回目"


def test_append_decision_log_rotation_disabled_when_max_bytes_not_positive(monkeypatch):
    monkeypatch.setattr(config, "AI_LOG_MAX_BYTES", 0)
    file_path = config.decision_log_file_path("USDJPY")

    for i in range(3):
        ai_status.append_decision_log(Signal("WAIT", f"{i}回目", {}, confidence=0), "USDJPY", "M15")

    assert not file_path.with_name(f"{file_path.stem}.1{file_path.suffix}").exists()
    assert len(file_path.read_text(encoding="utf-8").splitlines()) == 3


def test_append_shadow_log_also_rotates(monkeypatch):
    monkeypatch.setattr(config, "AI_LOG_MAX_BYTES", 1)
    monkeypatch.setattr(config, "AI_LOG_BACKUP_COUNT", 3)
    rule_signal = Signal("WAIT", "ルール", {}, confidence=0)
    shadow_signal = Signal("BUY", "シャドー", {}, confidence=80)

    ai_status.append_shadow_log(rule_signal, shadow_signal, "USDJPY", "M15", 150.0)
    ai_status.append_shadow_log(rule_signal, shadow_signal, "USDJPY", "M15", 150.5)

    file_path = config.shadow_log_file_path("USDJPY")
    archived = file_path.with_name(f"{file_path.stem}.1{file_path.suffix}")
    assert archived.exists()
    assert len(file_path.read_text(encoding="utf-8").splitlines()) == 1
