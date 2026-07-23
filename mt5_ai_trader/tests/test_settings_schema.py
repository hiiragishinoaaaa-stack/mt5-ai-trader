"""settings_schema.py の単体テスト。MT5/EA/実サーバー不要。"""
from __future__ import annotations

import json

import pytest

import config
import settings_schema


@pytest.fixture(autouse=True)
def _patch_config_json_path(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_JSON_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "RSI_OVERBOUGHT", 70.0)
    monkeypatch.setattr(config, "RSI_OVERSOLD", 30.0)
    monkeypatch.setattr(config, "EMA_FAST_PERIOD", 9)
    monkeypatch.setattr(config, "EMA_SLOW_PERIOD", 21)


# --- validate: 正常系 -------------------------------------------------------


def test_validate_accepts_all_valid_fields():
    payload = {
        "ORDER_VOLUME": 0.05,
        "SL_POINTS": 150,
        "TP_POINTS": 300,
        "MAX_CONCURRENT_POSITIONS": 3,
        "TIMEFRAME": "H1",
        "LOOP_INTERVAL_SECONDS": 30,
        "RSI_OVERBOUGHT": 72.0,
        "RSI_OVERSOLD": 28.0,
        "EMA_FAST_PERIOD": 5,
        "EMA_SLOW_PERIOD": 20,
        "ENABLE_ORDERS": True,
        "DEMO_ONLY": True,
        "BOT_RUN_STATE": "STOPPED",
        "DISCORD_NOTIFY_DAILY_SUMMARY": True,
        "AI_ENGINE": "openai",
    }

    cleaned, errors = settings_schema.validate(payload)

    assert errors == {}
    assert cleaned["ORDER_VOLUME"] == 0.05
    assert cleaned["TIMEFRAME"] == "H1"
    assert cleaned["ENABLE_ORDERS"] is True
    assert cleaned["BOT_RUN_STATE"] == "STOPPED"
    assert cleaned["DISCORD_NOTIFY_DAILY_SUMMARY"] is True
    assert cleaned["AI_ENGINE"] == "openai"
    assert cleaned["MAX_CONCURRENT_POSITIONS"] == 3


@pytest.mark.parametrize(
    "payload",
    [
        {"MAX_CONCURRENT_POSITIONS": 0},  # min(1)未満
        {"MAX_CONCURRENT_POSITIONS": 11},  # max(10)超過
    ],
)
def test_validate_rejects_out_of_range_max_concurrent_positions(payload):
    cleaned, errors = settings_schema.validate(payload)

    assert "MAX_CONCURRENT_POSITIONS" in errors
    assert "MAX_CONCURRENT_POSITIONS" not in cleaned


def test_validate_ignores_unknown_keys():
    cleaned, errors = settings_schema.validate({"SOME_FUTURE_FIELD": 123, "ORDER_VOLUME": 0.02})

    assert errors == {}
    assert "SOME_FUTURE_FIELD" not in cleaned
    assert cleaned["ORDER_VOLUME"] == 0.02


# --- validate: 型・範囲チェック ----------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"ORDER_VOLUME": 0.0},  # min未満
        {"ORDER_VOLUME": 1000.0},  # max超過
        {"SL_POINTS": -1},
        {"TP_POINTS": -1},
        {"LOOP_INTERVAL_SECONDS": 1},  # min未満(5秒未満)
        {"LOOP_INTERVAL_SECONDS": 999999},  # max超過
        {"RSI_OVERBOUGHT": 10.0},  # min(50)未満
        {"RSI_OVERSOLD": 60.0},  # max(50)超過
        {"EMA_FAST_PERIOD": 0},  # min未満
        {"EMA_SLOW_PERIOD": 1},  # min(2)未満
    ],
)
def test_validate_rejects_out_of_range_values(payload):
    cleaned, errors = settings_schema.validate(payload)

    key = next(iter(payload))
    assert key in errors
    assert key not in cleaned


def test_validate_rejects_invalid_timeframe_choice():
    cleaned, errors = settings_schema.validate({"TIMEFRAME": "M2"})

    assert "TIMEFRAME" in errors
    assert "TIMEFRAME" not in cleaned


def test_validate_rejects_invalid_entry_strictness_choice():
    cleaned, errors = settings_schema.validate({"ENTRY_STRICTNESS": "extreme"})

    assert "ENTRY_STRICTNESS" in errors


def test_validate_accepts_all_bot_run_state_choices():
    for choice in settings_schema.BOT_RUN_STATE_CHOICES:
        cleaned, errors = settings_schema.validate({"BOT_RUN_STATE": choice})

        assert errors == {}
        assert cleaned["BOT_RUN_STATE"] == choice


def test_validate_rejects_invalid_bot_run_state_choice():
    cleaned, errors = settings_schema.validate({"BOT_RUN_STATE": "PAUSED"})

    assert "BOT_RUN_STATE" in errors
    assert "BOT_RUN_STATE" not in cleaned


def test_validate_accepts_all_ai_engine_choices():
    for choice in settings_schema.AI_ENGINE_CHOICES:
        cleaned, errors = settings_schema.validate({"AI_ENGINE": choice})

        assert errors == {}
        assert cleaned["AI_ENGINE"] == choice


def test_validate_rejects_invalid_ai_engine_choice():
    cleaned, errors = settings_schema.validate({"AI_ENGINE": "mistral"})

    assert "AI_ENGINE" in errors
    assert "AI_ENGINE" not in cleaned


def test_validate_ignores_api_key_fields_not_in_schema():
    """OPENAI_API_KEY/ANTHROPIC_API_KEYはセキュリティ上FIELDSに含まれず、
    payloadに入っていても無視される(current_settings()にも出てこない)。
    """
    cleaned, errors = settings_schema.validate({"OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": "sk-ant-test"})

    assert cleaned == {}
    assert errors == {}
    assert "OPENAI_API_KEY" not in settings_schema.FIELDS
    assert "ANTHROPIC_API_KEY" not in settings_schema.FIELDS


def test_validate_rejects_wrong_type():
    cleaned, errors = settings_schema.validate({"ORDER_VOLUME": "not-a-number"})

    assert "ORDER_VOLUME" in errors


def test_validate_rejects_bool_for_numeric_field():
    """PythonではTrue/Falseがintのサブクラスなので、意図しない誤入力を防ぐため明示的に拒否する。"""
    cleaned, errors = settings_schema.validate({"SL_POINTS": True})

    assert "SL_POINTS" in errors


# --- validate: RSI/EMAの相互関係チェック -------------------------------------


def test_validate_rejects_rsi_overbought_not_greater_than_oversold():
    # 両方とも単体の範囲チェック(overbought:50-100 / oversold:0-50)は通るが、
    # overbought(50) <= oversold(50) となり相互関係チェックで弾かれるケース。
    cleaned, errors = settings_schema.validate({"RSI_OVERBOUGHT": 50.0, "RSI_OVERSOLD": 50.0})

    assert "RSI_OVERBOUGHT" in errors
    assert "RSI_OVERBOUGHT" not in cleaned
    assert "RSI_OVERSOLD" not in cleaned


def test_validate_rsi_overbought_checked_against_existing_config_value():
    """片方だけ送られてきた場合、既存のconfig値と突き合わせて矛盾を検出する。"""
    # 既存(fixtureで固定): RSI_OVERSOLD=30.0。overbought=25はそれより小さく矛盾。
    cleaned, errors = settings_schema.validate({"RSI_OVERBOUGHT": 25.0})

    assert "RSI_OVERBOUGHT" in errors


def test_validate_rejects_ema_fast_not_less_than_slow():
    cleaned, errors = settings_schema.validate({"EMA_FAST_PERIOD": 30, "EMA_SLOW_PERIOD": 10})

    assert "EMA_FAST_PERIOD" in errors
    assert "EMA_FAST_PERIOD" not in cleaned
    assert "EMA_SLOW_PERIOD" not in cleaned


# --- Entry Strictness ---------------------------------------------------------


def test_entry_strictness_populates_rsi_thresholds_when_not_explicit():
    cleaned, errors = settings_schema.validate({"ENTRY_STRICTNESS": "aggressive"})

    assert errors == {}
    assert cleaned["ENTRY_STRICTNESS"] == "aggressive"
    preset = settings_schema.ENTRY_STRICTNESS_PRESETS["aggressive"]
    assert cleaned["RSI_BUY_MIN"] == preset["RSI_BUY_MIN"]
    assert cleaned["RSI_BUY_MAX"] == preset["RSI_BUY_MAX"]
    assert cleaned["RSI_SELL_MIN"] == preset["RSI_SELL_MIN"]
    assert cleaned["RSI_SELL_MAX"] == preset["RSI_SELL_MAX"]
    assert cleaned["REQUIRED_SCORE"] == preset["REQUIRED_SCORE"]


def test_entry_strictness_active_m5_cascades_timeframe_and_atr_settings():
    cleaned, errors = settings_schema.validate({"ENTRY_STRICTNESS": "active_m5"})

    assert errors == {}
    preset = settings_schema.ENTRY_STRICTNESS_PRESETS["active_m5"]
    for key, value in preset.items():
        assert cleaned[key] == value


def test_rsi_buy_min_must_be_less_than_max():
    cleaned, errors = settings_schema.validate({"RSI_BUY_MIN": 70.0, "RSI_BUY_MAX": 60.0})

    assert "RSI_BUY_MIN" in errors
    assert "RSI_BUY_MIN" not in cleaned
    assert "RSI_BUY_MAX" not in cleaned


def test_entry_strictness_does_not_override_explicit_rsi_values():
    cleaned, errors = settings_schema.validate(
        {"ENTRY_STRICTNESS": "aggressive", "RSI_OVERBOUGHT": 90.0, "RSI_OVERSOLD": 10.0}
    )

    assert errors == {}
    assert cleaned["RSI_OVERBOUGHT"] == 90.0
    assert cleaned["RSI_OVERSOLD"] == 10.0


# --- save / current_settings --------------------------------------------------


def test_save_creates_config_json_and_current_settings_reflects_it():
    settings_schema.save({"ORDER_VOLUME": 0.03, "ENABLE_ORDERS": True})

    assert config.CONFIG_JSON_PATH.exists()
    on_disk = json.loads(config.CONFIG_JSON_PATH.read_text(encoding="utf-8"))
    assert on_disk["ORDER_VOLUME"] == 0.03
    assert on_disk["ENABLE_ORDERS"] is True

    current = settings_schema.current_settings()
    assert current["ORDER_VOLUME"] == 0.03
    assert current["ENABLE_ORDERS"] is True


def test_save_merges_with_existing_config_json_without_dropping_fields():
    settings_schema.save({"ORDER_VOLUME": 0.02})
    settings_schema.save({"SL_POINTS": 250})

    on_disk = json.loads(config.CONFIG_JSON_PATH.read_text(encoding="utf-8"))
    assert on_disk["ORDER_VOLUME"] == 0.02  # 1回目の値が保持されている
    assert on_disk["SL_POINTS"] == 250
