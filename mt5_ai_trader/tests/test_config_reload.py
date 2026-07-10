"""config.py の config.json ホットリロード機構(load_config_json)のテスト。"""
from __future__ import annotations

import json
import os
import time

import config


def _write_config_json(path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")
    # 同じファイルシステムのタイムスタンプ解像度によっては、直後の書き込みで
    # mtimeが変わらないことがあるため、明示的に少し先の時刻へ更新しておく。
    future = time.time() + 1
    os.utime(path, (future, future))


def test_load_config_json_applies_overrides(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "ORDER_VOLUME", 0.01)
    monkeypatch.setattr(config, "CONFIG_JSON_PATH", path)

    _write_config_json(path, {"ORDER_VOLUME": 0.08, "TIMEFRAME": "H4"})

    changed = config.load_config_json(force=True)

    assert changed is True
    assert config.ORDER_VOLUME == 0.08
    assert config.TIMEFRAME == "H4"


def test_load_config_json_returns_false_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_JSON_PATH", tmp_path / "does_not_exist.json")

    changed = config.load_config_json(force=True)

    assert changed is False


def test_load_config_json_skips_reload_when_mtime_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_JSON_PATH", path)
    monkeypatch.setattr(config, "_config_json_mtime", None)

    _write_config_json(path, {"SL_POINTS": 111})
    first = config.load_config_json()
    assert first is True
    assert config.SL_POINTS == 111

    # ファイルを変更しないまま再度呼んでも、mtimeが同じなら再読込しない。
    second = config.load_config_json()
    assert second is False


def test_load_config_json_detects_new_mtime_after_change(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_JSON_PATH", path)
    monkeypatch.setattr(config, "_config_json_mtime", None)

    _write_config_json(path, {"TP_POINTS": 300})
    assert config.load_config_json() is True
    assert config.TP_POINTS == 300

    time.sleep(0.05)
    _write_config_json(path, {"TP_POINTS": 500})
    assert config.load_config_json() is True
    assert config.TP_POINTS == 500


def test_load_config_json_ignores_unknown_keys(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_JSON_PATH", path)

    _write_config_json(path, {"NOT_A_REAL_SETTING": "whatever"})

    # 例外を送出せず、単に無視される。
    assert config.load_config_json(force=True) is True
    assert not hasattr(config, "NOT_A_REAL_SETTING")


def test_load_config_json_skips_invalid_type_without_crashing(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "ORDER_VOLUME", 0.01)
    monkeypatch.setattr(config, "CONFIG_JSON_PATH", path)

    _write_config_json(path, {"ORDER_VOLUME": "not-a-number", "SL_POINTS": 222})

    assert config.load_config_json(force=True) is True
    assert config.ORDER_VOLUME == 0.01  # 不正な値は無視され、既存値のまま
    assert config.SL_POINTS == 222  # 他の妥当な値は反映される


def test_load_config_json_ignores_malformed_json(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_JSON_PATH", path)

    path.write_text("{not valid json", encoding="utf-8")

    assert config.load_config_json(force=True) is False
