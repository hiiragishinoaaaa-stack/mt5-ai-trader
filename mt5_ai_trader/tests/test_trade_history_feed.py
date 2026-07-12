"""trade_history_feed.py の単体テスト。MT5/EA/実ファイルシステムのMT5パス不要。

config.TRADE_HISTORY_FILE_PATH を一時ファイルに差し替えてテストする。
"""
from __future__ import annotations

import json
import time

import pytest

import config
import trade_history_feed


def _trade(**overrides) -> dict:
    base = {
        "position_id": 1,
        "symbol": "USDJPY",
        "type": "BUY",
        "volume": 0.01,
        "price_open": 157.100,
        "price_close": 157.244,
        "profit": 4320.0,
        "open_time": int(time.time()) - 7200,
        "close_time": int(time.time()) - 3600,
        "magic": 990101,
        "is_artemis": True,
    }
    base.update(overrides)
    return base


def _write_payload(path, trades, **overrides):
    payload = {"updated_at": time.time(), "trades": trades}
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture(autouse=True)
def _patch_trade_history_path(tmp_path, monkeypatch):
    file_path = tmp_path / "artemis_trade_history.json"
    monkeypatch.setattr(config, "TRADE_HISTORY_FILE_PATH", file_path)
    return file_path


def test_read_history_success():
    file_path = config.TRADE_HISTORY_FILE_PATH
    _write_payload(file_path, [_trade()])

    feed = trade_history_feed.FileTradeHistoryFeed()
    trades = feed.read_history()

    assert len(trades) == 1
    assert trades[0].symbol == "USDJPY"
    assert trades[0].profit == 4320.0
    assert trades[0].is_artemis is True


def test_read_history_sorts_newest_first():
    file_path = config.TRADE_HISTORY_FILE_PATH
    older = _trade(position_id=1, close_time=int(time.time()) - 7200)
    newer = _trade(position_id=2, close_time=int(time.time()) - 60)
    _write_payload(file_path, [older, newer])

    feed = trade_history_feed.FileTradeHistoryFeed()
    trades = feed.read_history()

    assert [t.position_id for t in trades] == [2, 1]


def test_read_history_empty_list_ok():
    file_path = config.TRADE_HISTORY_FILE_PATH
    _write_payload(file_path, [])

    feed = trade_history_feed.FileTradeHistoryFeed()
    trades = feed.read_history()

    assert trades == []


def test_read_history_missing_file_raises():
    feed = trade_history_feed.FileTradeHistoryFeed()
    with pytest.raises(trade_history_feed.TradeHistoryError, match="見つかりません"):
        feed.read_history()


def test_read_history_stale_data_raises():
    file_path = config.TRADE_HISTORY_FILE_PATH
    _write_payload(file_path, [_trade()], updated_at=time.time() - 999)

    feed = trade_history_feed.FileTradeHistoryFeed()
    with pytest.raises(trade_history_feed.TradeHistoryError, match="古すぎます"):
        feed.read_history(max_staleness_seconds=30)


def test_read_history_corrupted_json_raises():
    file_path = config.TRADE_HISTORY_FILE_PATH
    file_path.write_text("{not valid json", encoding="utf-8")

    feed = trade_history_feed.FileTradeHistoryFeed()
    with pytest.raises(trade_history_feed.TradeHistoryError):
        feed.read_history()
