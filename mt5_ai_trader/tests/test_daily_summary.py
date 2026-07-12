"""daily_summary.py の単体テスト。Discordへは実際に送信しない
(discord_notifier.notify_daily_summaryをモックする)。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pytest

import config
import daily_summary
import discord_notifier
import trade_history_feed


def _trade(**overrides) -> dict:
    base = {
        "position_id": 1,
        "symbol": "USDJPY",
        "type": "BUY",
        "volume": 0.01,
        "price_open": 157.100,
        "price_close": 157.244,
        "profit": 1000.0,
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
    monkeypatch.setattr(config, "DAILY_SUMMARY_STATE_FILE_PATH", tmp_path / "artemis_daily_summary_state.json")
    monkeypatch.setattr(config, "DISCORD_ENABLED", True)
    monkeypatch.setattr(config, "DISCORD_NOTIFY_DAILY_SUMMARY", True)
    monkeypatch.setattr(config, "DAILY_SUMMARY_HOUR", 13)


def _write_trades(trades: list[dict]) -> None:
    payload = {"updated_at": time.time(), "trades": trades}
    config.TRADE_HISTORY_FILE_PATH.write_text(json.dumps(payload), encoding="utf-8")


def _now(hour: int, day: int = 12) -> datetime:
    return datetime(2026, 7, day, hour, 30, tzinfo=timezone.utc)


def test_skips_when_discord_disabled(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_ENABLED", False)
    calls = []
    monkeypatch.setattr(discord_notifier, "notify_daily_summary", lambda *a: calls.append(a))
    _write_trades([_trade()])

    daily_summary.maybe_send_daily_summary(trade_history_feed.FileTradeHistoryFeed(), now=_now(14))

    assert calls == []


def test_skips_when_notify_daily_summary_disabled(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_NOTIFY_DAILY_SUMMARY", False)
    calls = []
    monkeypatch.setattr(discord_notifier, "notify_daily_summary", lambda *a: calls.append(a))
    _write_trades([_trade()])

    daily_summary.maybe_send_daily_summary(trade_history_feed.FileTradeHistoryFeed(), now=_now(14))

    assert calls == []


def test_skips_before_daily_summary_hour(monkeypatch):
    calls = []
    monkeypatch.setattr(discord_notifier, "notify_daily_summary", lambda *a: calls.append(a))
    _write_trades([_trade()])

    daily_summary.maybe_send_daily_summary(trade_history_feed.FileTradeHistoryFeed(), now=_now(10))

    assert calls == []


def test_sends_once_after_hour_and_computes_stats(monkeypatch):
    calls = []
    monkeypatch.setattr(discord_notifier, "notify_daily_summary", lambda *a: calls.append(a))
    now = _now(14)
    today_epoch = int(now.timestamp())
    _write_trades(
        [
            _trade(position_id=1, profit=1000.0, close_time=today_epoch - 3600),
            _trade(position_id=2, profit=-400.0, close_time=today_epoch - 1800),
            # 前日分(集計に含めない)
            _trade(position_id=3, profit=99999.0, close_time=today_epoch - 90000),
        ]
    )

    daily_summary.maybe_send_daily_summary(trade_history_feed.FileTradeHistoryFeed(), now=now)

    assert len(calls) == 1
    date_str, total_profit, trade_count, win_rate = calls[0]
    assert date_str == "2026-07-12"
    assert total_profit == 600.0
    assert trade_count == 2
    assert win_rate == 50.0


def test_does_not_resend_same_day(monkeypatch):
    calls = []
    monkeypatch.setattr(discord_notifier, "notify_daily_summary", lambda *a: calls.append(a))
    _write_trades([_trade()])
    feed = trade_history_feed.FileTradeHistoryFeed()

    daily_summary.maybe_send_daily_summary(feed, now=_now(14))
    daily_summary.maybe_send_daily_summary(feed, now=_now(20))

    assert len(calls) == 1


def test_sends_again_on_next_day(monkeypatch):
    calls = []
    monkeypatch.setattr(discord_notifier, "notify_daily_summary", lambda *a: calls.append(a))
    _write_trades([_trade(close_time=int(_now(14).timestamp()))])
    feed = trade_history_feed.FileTradeHistoryFeed()

    daily_summary.maybe_send_daily_summary(feed, now=_now(14, day=12))
    _write_trades([_trade(close_time=int(_now(14, day=13).timestamp()))])
    daily_summary.maybe_send_daily_summary(feed, now=_now(14, day=13))

    assert len(calls) == 2


def test_skips_when_trade_history_unavailable(monkeypatch):
    calls = []
    monkeypatch.setattr(discord_notifier, "notify_daily_summary", lambda *a: calls.append(a))
    # 取引履歴ファイルを書き出さない(TradeHistoryErrorになる)。

    daily_summary.maybe_send_daily_summary(trade_history_feed.FileTradeHistoryFeed(), now=_now(14))

    assert calls == []
    assert not config.DAILY_SUMMARY_STATE_FILE_PATH.exists()
