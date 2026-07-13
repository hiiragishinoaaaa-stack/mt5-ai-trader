"""ea_config_writer.py の単体テスト。"""
from __future__ import annotations

import json

import pytest

import config
import ea_config_writer


@pytest.fixture(autouse=True)
def _patch_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EA_CONFIG_FILE_PATH", tmp_path / "artemis_ea_config.json")


def test_write_ea_config_writes_timeframe():
    ea_config_writer.write_ea_config("M1")

    payload = json.loads(config.EA_CONFIG_FILE_PATH.read_text(encoding="utf-8"))
    assert payload["timeframe"] == "M1"
    assert "updated_at" in payload


def test_write_ea_config_overwrites_previous_value():
    ea_config_writer.write_ea_config("M15")
    ea_config_writer.write_ea_config("M1")

    payload = json.loads(config.EA_CONFIG_FILE_PATH.read_text(encoding="utf-8"))
    assert payload["timeframe"] == "M1"


def test_write_ea_config_creates_parent_dir(tmp_path, monkeypatch):
    nested = tmp_path / "nested" / "dir" / "artemis_ea_config.json"
    monkeypatch.setattr(config, "EA_CONFIG_FILE_PATH", nested)

    ea_config_writer.write_ea_config("H1")

    assert nested.exists()
    assert json.loads(nested.read_text(encoding="utf-8"))["timeframe"] == "H1"
