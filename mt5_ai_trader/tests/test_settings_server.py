"""settings_server.py の結合テスト。実際にHTTPサーバーをテスト用ポートで
起動し、標準ライブラリのurllibでリクエストを送って検証する。
MT5/EA/実ファイルシステムのMT5パスは不要。
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

import config
import settings_server


def _request(url: str, method: str = "GET", payload: dict | None = None, token: str | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), resp.headers
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, (json.loads(body) if body else {}), exc.headers


def _start_server():
    server = settings_server.ThreadingHTTPServer(("127.0.0.1", 0), settings_server.SettingsRequestHandler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://{host}:{port}"


def _stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.fixture()
def base_url(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_JSON_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "SETTINGS_API_TOKEN", "")
    monkeypatch.setattr(config, "ENABLE_ORDERS", False)
    monkeypatch.setattr(config, "DEMO_ONLY", False)
    monkeypatch.setattr(config, "ACCOUNT_STATE_FILE_PATH", tmp_path / "artemis_account_state.json")
    monkeypatch.setattr(config, "AI_STATUS_FILE_PATH", tmp_path / "artemis_ai_status.json")
    monkeypatch.setattr(config, "TRADE_HISTORY_FILE_PATH", tmp_path / "artemis_trade_history.json")
    monkeypatch.setattr(config, "CLOSE_REQUEST_FILE_PATH", tmp_path / "artemis_close_request.json")
    monkeypatch.setattr(config, "CLOSE_RESULT_FILE_PATH", tmp_path / "artemis_close_result.json")
    monkeypatch.setattr(config, "SYMBOL", "USDJPY")
    monkeypatch.setattr(config, "ORDER_RESULT_WAIT_SECONDS", 2.0)

    server, thread, url = _start_server()
    try:
        yield url
    finally:
        _stop_server(server, thread)


def test_get_settings_returns_current_values(base_url):
    status, body, _ = _request(f"{base_url}/api/settings")

    assert status == 200
    assert body["settings"]["ENABLE_ORDERS"] is False


def test_post_settings_updates_and_persists(base_url):
    status, body, _ = _request(
        f"{base_url}/api/settings",
        method="POST",
        payload={"ORDER_VOLUME": 0.04, "ENABLE_ORDERS": True},
    )

    assert status == 200
    assert body["success"] is True
    assert body["settings"]["ORDER_VOLUME"] == 0.04
    assert body["settings"]["ENABLE_ORDERS"] is True
    assert config.ORDER_VOLUME == 0.04
    assert config.ENABLE_ORDERS is True
    assert config.CONFIG_JSON_PATH.exists()


def test_post_settings_rejects_out_of_range_value(base_url):
    status, body, _ = _request(f"{base_url}/api/settings", method="POST", payload={"ORDER_VOLUME": -5})

    assert status == 400
    assert body["success"] is False
    assert "ORDER_VOLUME" in body["errors"]
    assert not config.CONFIG_JSON_PATH.exists()  # 不正な値は保存されない


def test_post_settings_rejects_malformed_json(base_url):
    req = urllib.request.Request(
        f"{base_url}/api/settings",
        data=b"{not valid json",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5)
    assert exc_info.value.code == 400


def test_unknown_path_returns_404(base_url):
    status, _, _ = _request(f"{base_url}/api/unknown")
    assert status == 404


def test_options_preflight_has_cors_headers(base_url):
    req = urllib.request.Request(f"{base_url}/api/settings", method="OPTIONS")
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 204
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"


def test_token_required_when_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_JSON_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "SETTINGS_API_TOKEN", "secret123")

    server, thread, url = _start_server()
    try:
        status_no_token, _, _ = _request(f"{url}/api/settings")
        assert status_no_token == 401

        status_with_token, body, _ = _request(f"{url}/api/settings", token="secret123")
        assert status_with_token == 200
        assert "settings" in body
    finally:
        _stop_server(server, thread)


def test_get_account_returns_state(base_url):
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
        "positions": [],
    }
    config.ACCOUNT_STATE_FILE_PATH.write_text(json.dumps(payload), encoding="utf-8")

    status, body, _ = _request(f"{base_url}/api/account")

    assert status == 200
    assert body["account"]["balance"] == 10000.0
    assert body["positions"] == []
    assert body["target_symbol"] == config.SYMBOL


def test_get_account_missing_file_returns_503(base_url):
    status, body, _ = _request(f"{base_url}/api/account")

    assert status == 503
    assert "error" in body


def test_get_account_requires_token_when_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_JSON_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "ACCOUNT_STATE_FILE_PATH", tmp_path / "artemis_account_state.json")
    monkeypatch.setattr(config, "SETTINGS_API_TOKEN", "secret123")

    server, thread, url = _start_server()
    try:
        status_no_token, _, _ = _request(f"{url}/api/account")
        assert status_no_token == 401
    finally:
        _stop_server(server, thread)


def test_get_ai_status_returns_latest_decision(base_url):
    payload = {
        "action": "BUY",
        "confidence": 100,
        "reason": "テスト理由",
        "symbol": "USDJPY",
        "timeframe": "M15",
        "updated_at": time.time(),
    }
    config.AI_STATUS_FILE_PATH.write_text(json.dumps(payload), encoding="utf-8")

    status, body, _ = _request(f"{base_url}/api/ai-status")

    assert status == 200
    assert body["action"] == "BUY"
    assert body["confidence"] == 100


def test_get_ai_status_missing_file_returns_503(base_url):
    status, body, _ = _request(f"{base_url}/api/ai-status")

    assert status == 503
    assert "error" in body


def test_get_trade_history_returns_trades(base_url):
    payload = {
        "updated_at": time.time(),
        "trades": [
            {
                "position_id": 1,
                "symbol": "USDJPY",
                "type": "BUY",
                "volume": 0.01,
                "price_open": 157.1,
                "price_close": 157.244,
                "profit": 4320.0,
                "open_time": int(time.time()) - 7200,
                "close_time": int(time.time()) - 3600,
                "magic": 990101,
                "is_artemis": True,
            }
        ],
    }
    config.TRADE_HISTORY_FILE_PATH.write_text(json.dumps(payload), encoding="utf-8")

    status, body, _ = _request(f"{base_url}/api/trade-history")

    assert status == 200
    assert len(body["trades"]) == 1
    assert body["trades"][0]["symbol"] == "USDJPY"


def test_get_trade_history_missing_file_returns_503(base_url):
    status, body, _ = _request(f"{base_url}/api/trade-history")

    assert status == 503
    assert "error" in body


def test_close_position_rejects_when_enable_orders_false(base_url):
    # base_url fixtureの既定でENABLE_ORDERS=False。
    status, body, _ = _request(f"{base_url}/api/close-position", method="POST")

    assert status == 409
    assert body["success"] is False
    assert not config.CLOSE_REQUEST_FILE_PATH.exists()


def test_close_position_rejects_when_demo_only_false(base_url, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_ORDERS", True)
    # DEMO_ONLYはbase_url fixtureの既定でFalseのまま。

    status, body, _ = _request(f"{base_url}/api/close-position", method="POST")

    assert status == 409
    assert body["success"] is False
    assert not config.CLOSE_REQUEST_FILE_PATH.exists()


def test_close_position_succeeds_when_ea_responds(base_url, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_ORDERS", True)
    monkeypatch.setattr(config, "DEMO_ONLY", True)

    def fake_ea():
        for _ in range(50):
            if config.CLOSE_REQUEST_FILE_PATH.exists():
                break
            time.sleep(0.02)
        request = json.loads(config.CLOSE_REQUEST_FILE_PATH.read_text(encoding="utf-8"))
        result = {
            "request_id": request["request_id"],
            "processed_at": time.time(),
            "success": True,
            "closed_count": 1,
            "message": "closed 1/1 position(s)",
        }
        config.CLOSE_RESULT_FILE_PATH.write_text(json.dumps(result), encoding="utf-8")

    t = threading.Thread(target=fake_ea)
    t.start()
    status, body, _ = _request(f"{base_url}/api/close-position", method="POST")
    t.join()

    assert status == 200
    assert body["success"] is True
    assert body["closed_count"] == 1


def test_close_position_times_out_when_ea_does_not_respond(base_url, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_ORDERS", True)
    monkeypatch.setattr(config, "DEMO_ONLY", True)
    monkeypatch.setattr(config, "ORDER_RESULT_WAIT_SECONDS", 0.3)

    status, body, _ = _request(f"{base_url}/api/close-position", method="POST")

    assert status == 409
    assert body["success"] is False
