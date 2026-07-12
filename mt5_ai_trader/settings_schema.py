"""ARTEMIS X Dashboard(Web管理画面)から変更できる売買設定の定義。

Dashboardの「Settings」画面、それを受け取るsettings_server.py、実行中に
設定を反映するconfig.py(load_config_json)の3者が共有する「唯一の正」の
定義。設定項目を追加・変更したい場合はこのファイルのFIELDSと
ENTRY_STRICTNESS_PRESETSだけを直せばよい。

このモジュールはconfig.pyから遅延import(関数内import)されるため、
モジュールの先頭でconfig.pyをimportしない(循環importになるため)。
config.pyの値が必要な関数の中でのみimportする。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

TIMEFRAME_CHOICES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")

# DashboardのHome画面のSTART/STOP/EMERGENCY STOPボタンと1:1対応する。
# STOPPED/EMERGENCY_STOPPEDのときmain.pyは判断・発注をスキップする
# (プロセス自体は動き続ける。詳細はmain.py run_once()を参照)。
BOT_RUN_STATE_CHOICES = ("RUNNING", "STOPPED", "EMERGENCY_STOPPED")

# Entry Strictness(エントリーの厳しさ)プリセット。選択するとRSI_OVERBOUGHT/
# RSI_OVERSOLDがこの値に上書きされる(payloadにRSI値も明示的に含まれていた
# 場合はそちらを優先する。validate()を参照)。
ENTRY_STRICTNESS_PRESETS: dict[str, dict[str, float]] = {
    "conservative": {"RSI_OVERBOUGHT": 65.0, "RSI_OVERSOLD": 35.0},
    "balanced": {"RSI_OVERBOUGHT": 70.0, "RSI_OVERSOLD": 30.0},
    "aggressive": {"RSI_OVERBOUGHT": 80.0, "RSI_OVERSOLD": 20.0},
}


@dataclass(frozen=True)
class FieldSpec:
    key: str
    type: type
    min_value: float | None = None
    max_value: float | None = None
    choices: tuple[str, ...] | None = None


# DashboardのSettings画面から変更できる項目一覧。
FIELDS: dict[str, FieldSpec] = {
    "ORDER_VOLUME": FieldSpec("ORDER_VOLUME", float, min_value=0.01, max_value=100.0),
    "SL_POINTS": FieldSpec("SL_POINTS", int, min_value=0, max_value=100_000),
    "TP_POINTS": FieldSpec("TP_POINTS", int, min_value=0, max_value=100_000),
    "TIMEFRAME": FieldSpec("TIMEFRAME", str, choices=TIMEFRAME_CHOICES),
    "LOOP_INTERVAL_SECONDS": FieldSpec("LOOP_INTERVAL_SECONDS", int, min_value=5, max_value=86_400),
    "RSI_OVERBOUGHT": FieldSpec("RSI_OVERBOUGHT", float, min_value=50.0, max_value=100.0),
    "RSI_OVERSOLD": FieldSpec("RSI_OVERSOLD", float, min_value=0.0, max_value=50.0),
    "EMA_FAST_PERIOD": FieldSpec("EMA_FAST_PERIOD", int, min_value=1, max_value=500),
    "EMA_SLOW_PERIOD": FieldSpec("EMA_SLOW_PERIOD", int, min_value=2, max_value=1000),
    "ENTRY_STRICTNESS": FieldSpec("ENTRY_STRICTNESS", str, choices=tuple(ENTRY_STRICTNESS_PRESETS)),
    "ENABLE_ORDERS": FieldSpec("ENABLE_ORDERS", bool),
    "DEMO_ONLY": FieldSpec("DEMO_ONLY", bool),
    "DISCORD_ENABLED": FieldSpec("DISCORD_ENABLED", bool),
    "DISCORD_WEBHOOK_URL": FieldSpec("DISCORD_WEBHOOK_URL", str),
    "DISCORD_NOTIFY_ON_TRADE": FieldSpec("DISCORD_NOTIFY_ON_TRADE", bool),
    "DISCORD_NOTIFY_ON_ERROR": FieldSpec("DISCORD_NOTIFY_ON_ERROR", bool),
    "BOT_RUN_STATE": FieldSpec("BOT_RUN_STATE", str, choices=BOT_RUN_STATE_CHOICES),
}


def coerce(raw_value: Any, spec: FieldSpec) -> Any:
    """raw_valueをspec.typeへ型変換する。失敗した場合TypeError/ValueErrorを送出する。"""
    if spec.type is bool:
        if isinstance(raw_value, bool):
            return raw_value
        raise TypeError("bool型である必要があります")
    if spec.type is int:
        if isinstance(raw_value, bool):
            raise TypeError("bool値はintとして扱いません")
        return int(raw_value)
    if spec.type is float:
        if isinstance(raw_value, bool):
            raise TypeError("bool値はfloatとして扱いません")
        return float(raw_value)
    if spec.type is str:
        if not isinstance(raw_value, str):
            raise TypeError("str型である必要があります")
        return raw_value
    raise TypeError(f"未対応の型です: {spec.type}")


def validate(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Dashboardから送られてきたpayloadを検証する。

    未知のキーは無視する(将来のフィールド追加・バージョン差異に寛容にする
    ため)。戻り値は (妥当な値のみを含む辞書, フィールド名->エラーメッセージ)。
    """
    import config  # 遅延import(config.py起動時のload_config_jsonとの循環importを避ける)

    cleaned: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for key, raw_value in payload.items():
        spec = FIELDS.get(key)
        if spec is None:
            continue

        try:
            value = coerce(raw_value, spec)
        except (TypeError, ValueError):
            errors[key] = f"{key}は{spec.type.__name__}型の値を指定してください"
            continue

        if spec.choices is not None and value not in spec.choices:
            errors[key] = f"{key}は次のいずれかを指定してください: {', '.join(spec.choices)}"
            continue

        if spec.min_value is not None and value < spec.min_value:
            errors[key] = f"{key}は{spec.min_value}以上である必要があります"
            continue
        if spec.max_value is not None and value > spec.max_value:
            errors[key] = f"{key}は{spec.max_value}以下である必要があります"
            continue

        cleaned[key] = value

    # Entry Strictnessのプリセットが指定され、RSI値が明示的には送られて
    # こなかった場合、プリセットに対応するRSI値を補う。
    if "ENTRY_STRICTNESS" in cleaned:
        preset = ENTRY_STRICTNESS_PRESETS[cleaned["ENTRY_STRICTNESS"]]
        cleaned.setdefault("RSI_OVERBOUGHT", preset["RSI_OVERBOUGHT"])
        cleaned.setdefault("RSI_OVERSOLD", preset["RSI_OVERSOLD"])

    # RSI/EMAの相互関係チェック。cleanedに無い側は現在の実効値(config.py)を使う。
    if "RSI_OVERBOUGHT" in cleaned or "RSI_OVERSOLD" in cleaned:
        overbought = cleaned.get("RSI_OVERBOUGHT", config.RSI_OVERBOUGHT)
        oversold = cleaned.get("RSI_OVERSOLD", config.RSI_OVERSOLD)
        if overbought <= oversold:
            errors["RSI_OVERBOUGHT"] = "RSI_OVERBOUGHTはRSI_OVERSOLDより大きい値にしてください"
            cleaned.pop("RSI_OVERBOUGHT", None)
            cleaned.pop("RSI_OVERSOLD", None)

    if "EMA_FAST_PERIOD" in cleaned or "EMA_SLOW_PERIOD" in cleaned:
        fast = cleaned.get("EMA_FAST_PERIOD", config.EMA_FAST_PERIOD)
        slow = cleaned.get("EMA_SLOW_PERIOD", config.EMA_SLOW_PERIOD)
        if fast >= slow:
            errors["EMA_FAST_PERIOD"] = "EMA_FAST_PERIODはEMA_SLOW_PERIODより小さい値にしてください"
            cleaned.pop("EMA_FAST_PERIOD", None)
            cleaned.pop("EMA_SLOW_PERIOD", None)

    return cleaned, errors


def current_settings() -> dict[str, Any]:
    """現在Pythonが使っている値(config.json + .env + 既定値)を返す。"""
    import config

    config.load_config_json()
    return {key: getattr(config, key) for key in FIELDS}


def save(cleaned: dict[str, Any]) -> None:
    """既存のconfig.jsonへcleanedをマージし、アトミックに書き込む。"""
    import config

    existing: dict[str, Any] = {}
    if config.CONFIG_JSON_PATH.exists():
        try:
            with config.CONFIG_JSON_PATH.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            existing = {}

    merged = {**existing, **cleaned}

    tmp_path = config.CONFIG_JSON_PATH.with_suffix(".tmp")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp_path.replace(config.CONFIG_JSON_PATH)
