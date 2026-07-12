"""claude_engine.py の単体テスト。実際にAnthropicへは接続しない
(urllib.request.urlopenをモックする)。
"""
from __future__ import annotations

import json
import urllib.error

import pandas as pd
import pytest

import config
import claude_engine


def _row(**overrides) -> dict:
    base = {
        "close": 150.0,
        "ema_fast": 151.0,
        "ema_slow": 150.0,
        "rsi": 55.0,
        "macd": 0.1,
        "macd_signal": 0.05,
        "macd_hist": 0.5,
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(config, "ANTHROPIC_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(config, "AI_ENGINE_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(config, "SYMBOL", "USDJPY")
    monkeypatch.setattr(config, "TIMEFRAME", "M15")


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _anthropic_response(action: str, reason: str = "test", confidence: int = 70) -> dict:
    text = json.dumps({"action": action, "reason": reason, "confidence": confidence})
    return {"content": [{"type": "text", "text": text}]}


def test_decide_returns_wait_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    engine = claude_engine.ClaudeEngine()

    signal = engine.decide(pd.DataFrame([_row()]))

    assert signal.action == "WAIT"
    assert "ANTHROPIC_API_KEY" in signal.reason


def test_decide_returns_wait_on_empty_dataframe():
    engine = claude_engine.ClaudeEngine()

    signal = engine.decide(pd.DataFrame())

    assert signal.action == "WAIT"


def test_decide_parses_successful_sell_response(monkeypatch):
    calls = []

    def _fake_urlopen(req, timeout=None):
        calls.append(req)
        return _FakeResponse(_anthropic_response("SELL", "下降トレンド", 65))

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    engine = claude_engine.ClaudeEngine()

    signal = engine.decide(pd.DataFrame([_row()]))

    assert len(calls) == 1
    assert calls[0].full_url == "https://api.anthropic.com/v1/messages"
    assert calls[0].get_header("X-api-key") == "sk-ant-test"
    assert calls[0].get_header("Anthropic-version") == "2023-06-01"
    assert signal.action == "SELL"
    assert signal.reason == "下降トレンド"
    assert signal.confidence == 65.0


def test_decide_falls_back_to_wait_on_network_error(monkeypatch):
    def _raise(req, timeout=None):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    engine = claude_engine.ClaudeEngine()

    signal = engine.decide(pd.DataFrame([_row()]))

    assert signal.action == "WAIT"
    assert "失敗" in signal.reason


def test_decide_falls_back_to_wait_on_malformed_response(monkeypatch):
    def _fake_urlopen(req, timeout=None):
        return _FakeResponse({"unexpected": "shape"})

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    engine = claude_engine.ClaudeEngine()

    signal = engine.decide(pd.DataFrame([_row()]))

    assert signal.action == "WAIT"


def test_decide_falls_back_to_wait_on_invalid_json_content(monkeypatch):
    def _fake_urlopen(req, timeout=None):
        return _FakeResponse({"content": [{"type": "text", "text": "not json at all"}]})

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    engine = claude_engine.ClaudeEngine()

    signal = engine.decide(pd.DataFrame([_row()]))

    assert signal.action == "WAIT"
