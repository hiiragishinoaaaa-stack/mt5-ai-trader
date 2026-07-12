"""account_feed.py の単体テスト。MT5/EA/実ファイルシステムのMT5パス不要。

config.ACCOUNT_STATE_FILE_PATH を一時ファイルに差し替えてテストする。
"""
from __future__ import annotations

import json
import time

import pytest

import account_feed
import config


def _write_payload(path, **overrides):
    payload = {
        "updated_at": time.time(),
        "account": {
            "login": 12345678,
            "currency": "USD",
            "balance": 10000.0,
            "equity": 9980.5,
            "margin": 50.0,
            "margin_free": 9930.5,
            "profit": -19.5,
        },
        "positions": [
            {
                "ticket": 111,
                "symbol": "USDJPY",
                "type": "BUY",
                "volume": 0.01,
                "price_open": 157.1,
                "price_current": 157.05,
                "sl": 156.9,
                "tp": 157.5,
                "profit": -5.0,
                "open_time": int(time.time()) - 3600,
                "magic": 990101,
                "is_artemis": True,
            }
        ],
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture(autouse=True)
def _patch_account_state_path(tmp_path, monkeypatch):
    file_path = tmp_path / "artemis_account_state.json"
    monkeypatch.setattr(config, "ACCOUNT_STATE_FILE_PATH", file_path)
    return file_path


def test_read_state_success():
    file_path = config.ACCOUNT_STATE_FILE_PATH
    _write_payload(file_path)

    feed = account_feed.FileAccountFeed()
    state = feed.read_state()

    assert state.account.balance == 10000.0
    assert state.account.equity == 9980.5
    assert len(state.positions) == 1
    assert state.positions[0].symbol == "USDJPY"
    assert state.positions[0].is_artemis is True


def test_read_state_no_positions():
    file_path = config.ACCOUNT_STATE_FILE_PATH
    _write_payload(file_path, positions=[])

    feed = account_feed.FileAccountFeed()
    state = feed.read_state()

    assert state.positions == []


def test_read_state_missing_file_raises():
    feed = account_feed.FileAccountFeed()
    with pytest.raises(account_feed.AccountFeedError, match="見つかりません"):
        feed.read_state()


def test_read_state_stale_data_raises():
    file_path = config.ACCOUNT_STATE_FILE_PATH
    _write_payload(file_path, updated_at=time.time() - 999)

    feed = account_feed.FileAccountFeed()
    with pytest.raises(account_feed.AccountFeedError, match="古すぎます"):
        feed.read_state(max_staleness_seconds=30)


def test_read_state_corrupted_json_raises():
    file_path = config.ACCOUNT_STATE_FILE_PATH
    file_path.write_text("{not valid json", encoding="utf-8")

    feed = account_feed.FileAccountFeed()
    with pytest.raises(account_feed.AccountFeedError):
        feed.read_state()


def test_read_state_missing_keys_raises():
    file_path = config.ACCOUNT_STATE_FILE_PATH
    file_path.write_text(json.dumps({"updated_at": time.time()}), encoding="utf-8")

    feed = account_feed.FileAccountFeed()
    with pytest.raises(account_feed.AccountFeedError, match="ありません"):
        feed.read_state()
