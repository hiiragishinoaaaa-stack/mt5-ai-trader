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
    monkeypatch.setattr(config, "DISCORD_NOTIFY_DAILY_SUMMARY", True)


def test_notify_trade_executed_sends_when_enabled(monkeypatch):
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: calls.append(req))

    discord_notifier.notify_trade_executed("BUY", "USDJPY", 0.01, 12345, "order sent")

    assert len(calls) == 1
    assert calls[0].full_url == "https://discord.example.com/webhook"


def test_send_sets_user_agent_to_avoid_cloudflare_403(monkeypatch):
    """discord.com手前のCloudflareは、urllib標準のUser-Agentを自動化アクセスとみなし
    403(error code: 1010)で拒否するため、ブラウザ相当のUser-Agentを送る必要がある。
    """
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: calls.append(req))

    discord_notifier.notify_trade_executed("BUY", "USDJPY", 0.01, 12345, "order sent")

    assert len(calls) == 1
    assert calls[0].get_header("User-agent") not in (None, "", "Python-urllib/3.12")


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


def test_notify_daily_summary_sends_when_enabled(monkeypatch):
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: calls.append(req))

    discord_notifier.notify_daily_summary("2026-07-12", 1234.5, 3, 66.7)

    assert len(calls) == 1


def test_notify_daily_summary_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_NOTIFY_DAILY_SUMMARY", False)
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: calls.append(req))

    discord_notifier.notify_daily_summary("2026-07-12", 1234.5, 3, 66.7)

    assert calls == []


def test_notify_does_not_raise_on_network_error(monkeypatch):
    def _raise(req, timeout=None):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr("urllib.request.urlopen", _raise)

    # 例外を送出せずログに警告を出すだけであることを確認する。
    discord_notifier.notify_trade_executed("BUY", "USDJPY", 0.01, 12345, "order sent")
