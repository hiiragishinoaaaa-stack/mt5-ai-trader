"""discord_notifier.py の単体テスト。実際にDiscordへは送信しない
(urllib.request.urlopenをモックする)。
"""
from __future__ import annotations

import urllib.error

import pytest

import config
import discord_notifier


@pytest.fixture(autouse=True)
def _patch_discord_config(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_ENABLED", True)
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "https://discord.example.com/webhook")
    monkeypatch.setattr(config, "DISCORD_NOTIFY_ON_TRADE", True)
    monkeypatch.setattr(config, "DISCORD_NOTIFY_ON_ERROR", True)


def test_notify_trade_executed_sends_when_enabled(monkeypatch):
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: calls.append(req))

    discord_notifier.notify_trade_executed("BUY", "USDJPY", 0.01, 12345, "order sent")

    assert len(calls) == 1
    assert calls[0].full_url == "https://discord.example.com/webhook"


def test_notify_trade_executed_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_ENABLED", False)
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: calls.append(req))

    discord_notifier.notify_trade_executed("BUY", "USDJPY", 0.01, 12345, "order sent")

    assert calls == []


def test_notify_trade_executed_skips_when_webhook_url_empty(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "")
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: calls.append(req))

    discord_notifier.notify_trade_executed("BUY", "USDJPY", 0.01, 12345, "order sent")

    assert calls == []


def test_notify_trade_executed_skips_when_notify_on_trade_false(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_NOTIFY_ON_TRADE", False)
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: calls.append(req))

    discord_notifier.notify_trade_executed("BUY", "USDJPY", 0.01, 12345, "order sent")

    assert calls == []


def test_notify_order_failed_sends_when_enabled(monkeypatch):
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: calls.append(req))

    discord_notifier.notify_order_failed("BUY", "USDJPY", "market closed")

    assert len(calls) == 1


def test_notify_does_not_raise_on_network_error(monkeypatch):
    def _raise(req, timeout=None):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr("urllib.request.urlopen", _raise)

    # 例外を送出せずログに警告を出すだけであることを確認する。
    discord_notifier.notify_trade_executed("BUY", "USDJPY", 0.01, 12345, "order sent")
