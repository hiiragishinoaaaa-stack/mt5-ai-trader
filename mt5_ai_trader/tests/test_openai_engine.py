"""openai_engine.py の単体テスト。実際にOpenAIへは接続しない
(urllib.request.urlopenをモックする)。
"""
from __future__ import annotations

import json
import urllib.error

import pandas as pd
import pytest

import config
import openai_engine


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
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(config, "OPENAI_MODEL", "gpt-4o-mini")
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


def _openai_response(action: str, reason: str = "test", confidence: int = 70) -> dict:
    content = json.dumps({"action": action, "reason": reason, "confidence": confidence})
    return {"choices": [{"message": {"content": content}}]}


def test_decide_returns_wait_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    engine = openai_engine.OpenAIEngine()

    signal = engine.decide(pd.DataFrame([_row()]))

    assert signal.action == "WAIT"
    assert "OPENAI_API_KEY" in signal.reason


def test_decide_returns_wait_on_empty_dataframe():
    engine = openai_engine.OpenAIEngine()

    signal = engine.decide(pd.DataFrame())

    assert signal.action == "WAIT"


def test_decide_parses_successful_buy_response(monkeypatch):
    calls = []

    def _fake_urlopen(req, timeout=None):
        calls.append(req)
        return _FakeResponse(_openai_response("BUY", "上昇トレンド", 80))

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    engine = openai_engine.OpenAIEngine()

    signal = engine.decide(pd.DataFrame([_row()]))

    assert len(calls) == 1
    assert calls[0].full_url == "https://api.openai.com/v1/chat/completions"
    assert calls[0].get_header("Authorization") == "Bearer sk-test"
    assert signal.action == "BUY"
    assert signal.reason == "上昇トレンド"
    assert signal.confidence == 80.0


def test_decide_falls_back_to_wait_on_network_error(monkeypatch):
    def _raise(req, timeout=None):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    engine = openai_engine.OpenAIEngine()

    signal = engine.decide(pd.DataFrame([_row()]))

    assert signal.action == "WAIT"
    assert "失敗" in signal.reason


def test_decide_falls_back_to_wait_on_malformed_response(monkeypatch):
    def _fake_urlopen(req, timeout=None):
        return _FakeResponse({"unexpected": "shape"})

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    engine = openai_engine.OpenAIEngine()

    signal = engine.decide(pd.DataFrame([_row()]))

    assert signal.action == "WAIT"


def test_decide_falls_back_to_wait_on_invalid_json_content(monkeypatch):
    def _fake_urlopen(req, timeout=None):
        return _FakeResponse({"choices": [{"message": {"content": "not json at all"}}]})

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    engine = openai_engine.OpenAIEngine()

    signal = engine.decide(pd.DataFrame([_row()]))

    assert signal.action == "WAIT"
