"""close_notifier.py の単体テスト。Discordへは実際に送信しない
(discord_notifier.notify_trade_closedをモックする)。
"""
from __future__ import annotations

import json
import time

import pytest

import close_notifier
import config
import discord_notifier
import trade_history_feed


def _trade(**overrides) -> dict:
    base = {
        "position_id": 1,
        "symbol": "USDJPY",
        "type": "BUY",
        "volume": 0.1,
        "price_open": 161.913,
        "price_close": 162.113,
        "profit": 2000.0,
        "open_time": int(time.time()) - 7200,
        "close_time": int(time.time()) - 3600,
        "magic": 990101,
        "is_artemis": True,
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _patch_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRADE_HISTORY_FILE_PATH", tmp_path / "artemis_trade_history.json")
    monkeypatch.setattr(config, "CLOSE_NOTIFIER_STATE_FILE_PATH", tmp_path / "artemis_close_notifier_state.json")
    monkeypatch.setattr(config, "DISCORD_ENABLED", True)
    monkeypatch.setattr(config, "DISCORD_NOTIFY_ON_TRADE", True)


def _write_trades(trades: list[dict]) -> None:
    payload = {"updated_at": time.time(), "trades": trades}
    config.TRADE_HISTORY_FILE_PATH.write_text(json.dumps(payload), encoding="utf-8")


def test_first_run_bootstraps_silently_without_notifying(monkeypatch):
    calls = []
    monkeypatch.setattr(discord_notifier, "notify_trade_closed", lambda t: calls.append(t))
    _write_trades([_trade(position_id=1, close_time=1000)])

    close_notifier.notify_newly_closed_trades(trade_history_feed.FileTradeHistoryFeed())

    assert calls == []  # 初回は既存分をまとめて通知しない(後追いスパム防止)
    assert config.CLOSE_NOTIFIER_STATE_FILE_PATH.exists()


def test_notifies_only_trades_closed_after_bootstrap(monkeypatch):
    calls = []
    monkeypatch.setattr(discord_notifier, "notify_trade_closed", lambda t: calls.append(t))
    feed = trade_history_feed.FileTradeHistoryFeed()

    _write_trades([_trade(position_id=1, close_time=1000)])
    close_notifier.notify_newly_closed_trades(feed)  # 初回: bootstrap only

    _write_trades(
        [
            _trade(position_id=1, close_time=1000),
            _trade(position_id=2, close_time=2000),
        ]
    )
    close_notifier.notify_newly_closed_trades(feed)  # 2回目: position_id=2だけ新規

    assert len(calls) == 1
    assert calls[0].position_id == 2


def test_does_not_renotify_same_trade(monkeypatch):
    calls = []
    monkeypatch.setattr(discord_notifier, "notify_trade_closed", lambda t: calls.append(t))
    feed = trade_history_feed.FileTradeHistoryFeed()

    _write_trades([_trade(position_id=1, close_time=1000)])
    close_notifier.notify_newly_closed_trades(feed)  # bootstrap

    _write_trades([_trade(position_id=1, close_time=1000), _trade(position_id=2, close_time=2000)])
    close_notifier.notify_newly_closed_trades(feed)
    close_notifier.notify_newly_closed_trades(feed)  # 同じ状態でもう一度

    assert len(calls) == 1


def test_notifies_multiple_new_trades_in_close_time_order(monkeypatch):
    calls = []
    monkeypatch.setattr(discord_notifier, "notify_trade_closed", lambda t: calls.append(t))
    feed = trade_history_feed.FileTradeHistoryFeed()

    _write_trades([_trade(position_id=1, close_time=1000)])
    close_notifier.notify_newly_closed_trades(feed)  # bootstrap

    _write_trades(
        [
            _trade(position_id=1, close_time=1000),
            _trade(position_id=3, close_time=3000),
            _trade(position_id=2, close_time=2000),
        ]
    )
    close_notifier.notify_newly_closed_trades(feed)

    assert [t.position_id for t in calls] == [2, 3]


def test_skips_silently_when_trade_history_unavailable(monkeypatch):
    calls = []
    monkeypatch.setattr(discord_notifier, "notify_trade_closed", lambda t: calls.append(t))
    # 取引履歴ファイルを書き出さない(TradeHistoryErrorになる)。

    close_notifier.notify_newly_closed_trades(trade_history_feed.FileTradeHistoryFeed())

    assert calls == []
    assert not config.CLOSE_NOTIFIER_STATE_FILE_PATH.exists()


def test_skips_silently_when_no_trades():
    _write_trades([])

    close_notifier.notify_newly_closed_trades(trade_history_feed.FileTradeHistoryFeed())

    assert not config.CLOSE_NOTIFIER_STATE_FILE_PATH.exists()
