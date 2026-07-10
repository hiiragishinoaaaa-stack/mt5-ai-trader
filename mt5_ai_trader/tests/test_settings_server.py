"""settings_server.py の結合テスト。実際にHTTPサーバーをテスト用ポートで
起動し、標準ライブラリのurllibでリクエストを送って検証する。
MT5/EA/実ファイルシステムのMT5パスは不要。
"""
from __future__ import annotations

import json
import threading
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
