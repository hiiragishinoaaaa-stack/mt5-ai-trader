"""ea_config_writer.py の単体テスト。"""
from __future__ import annotations

import json

import pytest

import config
import ea_config_writer


@pytest.fixture(autouse=True)
def _patch_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EA_CONFIG_FILE_PATH", tmp_path / "artemis_ea_config.json")


def test_write_ea_config_writes_timeframe_for_primary_symbol():
    ea_config_writer.write_ea_config("M1", config.SYMBOL)

    payload = json.loads(config.EA_CONFIG_FILE_PATH.read_text(encoding="utf-8"))
    assert payload["timeframe"] == "M1"
    assert "updated_at" in payload


def test_write_ea_config_overwrites_previous_value():
    ea_config_writer.write_ea_config("M15", config.SYMBOL)
    ea_config_writer.write_ea_config("M1", config.SYMBOL)

    payload = json.loads(config.EA_CONFIG_FILE_PATH.read_text(encoding="utf-8"))
    assert payload["timeframe"] == "M1"


def test_write_ea_config_creates_parent_dir(tmp_path, monkeypatch):
    nested = tmp_path / "nested" / "dir" / "artemis_ea_config.json"
    monkeypatch.setattr(config, "EA_CONFIG_FILE_PATH", nested)

    ea_config_writer.write_ea_config("H1", config.SYMBOL)

    assert nested.exists()
    assert json.loads(nested.read_text(encoding="utf-8"))["timeframe"] == "H1"


def test_write_ea_config_uses_separate_file_for_non_primary_symbol():
    """複数銘柄対応(Phase 12): プライマリ銘柄以外は別ファイルへ書き出す
    (別チャートに追加したEAインスタンスがそれぞれ自分のファイルだけを読む)。
    """
    ea_config_writer.write_ea_config("M15", config.SYMBOL)
    ea_config_writer.write_ea_config("M5", "EURUSD")

    primary_payload = json.loads(config.EA_CONFIG_FILE_PATH.read_text(encoding="utf-8"))
    assert primary_payload["timeframe"] == "M15"

    eurusd_path = config.ea_config_file_path("EURUSD")
    assert eurusd_path != config.EA_CONFIG_FILE_PATH
    eurusd_payload = json.loads(eurusd_path.read_text(encoding="utf-8"))
    assert eurusd_payload["timeframe"] == "M5"
