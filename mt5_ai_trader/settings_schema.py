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

# Dashboardの「銘柄」トグルで選べる候補一覧(Phase 12)。ここに無い銘柄は
# ENABLED_SYMBOLSに指定してもバリデーションエラーになる。新しい銘柄を
# 追加する場合はここへ追記し、MT5側にその銘柄用のEAインスタンスを
# (別チャートへ、入力パラメータだけ変えて)追加する。
AVAILABLE_SYMBOLS = ("USDJPY", "EURUSD")

# DashboardのSettings画面から選べるAI判断エンジン。OPENAI_API_KEY/
# ANTHROPIC_API_KEYはセキュリティ上の理由でFIELDSに含めない(.envでのみ設定、
# config.pyのコメント参照)。
AI_ENGINE_CHOICES = ("rule_based", "openai", "claude", "gemini")

# DashboardのHome画面のSTART/STOP/EMERGENCY STOPボタンと1:1対応する。
# STOPPED/EMERGENCY_STOPPEDのときmain.pyは判断・発注をスキップする
# (プロセス自体は動き続ける。詳細はmain.py run_once()を参照)。
BOT_RUN_STATE_CHOICES = ("RUNNING", "STOPPED", "EMERGENCY_STOPPED")

# Entry Strictness(エントリーの厳しさ)プリセット。選択すると、ここに列挙
# された各キーがconfig.jsonへ上書きされる(payloadに同じキーが明示的に
# 含まれていた場合はそちらを優先する。validate()を参照)。
#
# RuleBasedAIEngine(ai_engine.py)は「必須条件」(全て満たす必要がある)と
# 「加点条件」(REQUIRED_SCORE点以上でエントリー候補)の2段階でBUY/SELLを
# 判断する。RSI_BUY_MIN/MAX・RSI_SELL_MIN/MAX・REQUIRED_SCOREがこの判断の
# 主要パラメータで、プリセットが厳しくなるほどRSI帯域が狭く・必要スコアが
# 高くなる。conservativeのみ、直近5本の安値/高値を更新していないことを
# 追加の必須条件にする(REQUIRE_NO_NEW_EXTREME_5BARS)。
#
# active_m5は上記に加えてTIMEFRAME/EMA期間/ATRベースSL・TP/エントリー
# クールダウン/時間・日あたりの最大取引数もまとめて切り替える、USDJPY・M5
# での積極運用を想定したプリセット(詳細はREADME.mdの「複数銘柄対応」の後、
# 「M5アクティブ運用」セクションを参照)。
# REQUIRED_SCOREは、勝率優先ロジック(RuleBasedAIEngine、H1トレンドフィルター・
# 押し目待ち・MACD方向一致が必須条件化された後)のボーナス条件6点満点に
# 対する必要点数(MACD拡大は2026-07にボーナス条件へ格下げ。ai_engine.py
# 参照)。必須条件自体が以前よりずっと厳しくなっているため、各プリセットの
# REQUIRED_SCOREも底上げしている(aggressiveでも以前のbalanced相当以上)。
ENTRY_STRICTNESS_PRESETS: dict[str, dict[str, Any]] = {
    "conservative": {
        "RSI_BUY_MIN": 52.0,
        "RSI_BUY_MAX": 62.0,
        "RSI_SELL_MIN": 38.0,
        "RSI_SELL_MAX": 48.0,
        "REQUIRED_SCORE": 5,
        "REQUIRE_NO_NEW_EXTREME_5BARS": True,
    },
    "balanced": {
        "RSI_BUY_MIN": 50.0,
        "RSI_BUY_MAX": 65.0,
        "RSI_SELL_MIN": 35.0,
        "RSI_SELL_MAX": 50.0,
        "REQUIRED_SCORE": 4,
        "REQUIRE_NO_NEW_EXTREME_5BARS": False,
    },
    "aggressive": {
        "RSI_BUY_MIN": 45.0,
        "RSI_BUY_MAX": 75.0,
        "RSI_SELL_MIN": 25.0,
        "RSI_SELL_MAX": 55.0,
        "REQUIRED_SCORE": 3,
        "REQUIRE_NO_NEW_EXTREME_5BARS": False,
    },
    "active_m5": {
        "RSI_BUY_MIN": 48.0,
        "RSI_BUY_MAX": 68.0,
        "RSI_SELL_MIN": 32.0,
        "RSI_SELL_MAX": 52.0,
        "REQUIRED_SCORE": 4,
        "REQUIRE_NO_NEW_EXTREME_5BARS": False,
        "TIMEFRAME": "M5",
        "EMA_FAST_PERIOD": 20,
        "EMA_SLOW_PERIOD": 50,
        "RSI_PERIOD": 14,
        "ATR_PERIOD": 14,
        "LOOP_INTERVAL_SECONDS": 30,
        "ENTRY_COOLDOWN_SECONDS": 600,
        "MAX_CONCURRENT_POSITIONS": 1,
        "MAX_TRADES_PER_HOUR": 2,
        "MAX_TRADES_PER_DAY": 12,
        "STOP_MODE": "atr",
        "ATR_SL_MULTIPLIER": 1.2,
        "ATR_TP_MULTIPLIER": 1.8,
    },
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
    "MAX_CONCURRENT_POSITIONS": FieldSpec("MAX_CONCURRENT_POSITIONS", int, min_value=1, max_value=10),
    "TIMEFRAME": FieldSpec("TIMEFRAME", str, choices=TIMEFRAME_CHOICES),
    "LOOP_INTERVAL_SECONDS": FieldSpec("LOOP_INTERVAL_SECONDS", int, min_value=5, max_value=86_400),
    "RSI_OVERBOUGHT": FieldSpec("RSI_OVERBOUGHT", float, min_value=50.0, max_value=100.0),
    "RSI_OVERSOLD": FieldSpec("RSI_OVERSOLD", float, min_value=0.0, max_value=50.0),
    "EMA_FAST_PERIOD": FieldSpec("EMA_FAST_PERIOD", int, min_value=1, max_value=500),
    "EMA_SLOW_PERIOD": FieldSpec("EMA_SLOW_PERIOD", int, min_value=2, max_value=1000),
    "RSI_PERIOD": FieldSpec("RSI_PERIOD", int, min_value=2, max_value=200),
    "ATR_PERIOD": FieldSpec("ATR_PERIOD", int, min_value=2, max_value=200),
    "RSI_BUY_MIN": FieldSpec("RSI_BUY_MIN", float, min_value=0.0, max_value=100.0),
    "RSI_BUY_MAX": FieldSpec("RSI_BUY_MAX", float, min_value=0.0, max_value=100.0),
    "RSI_SELL_MIN": FieldSpec("RSI_SELL_MIN", float, min_value=0.0, max_value=100.0),
    "RSI_SELL_MAX": FieldSpec("RSI_SELL_MAX", float, min_value=0.0, max_value=100.0),
    "REQUIRED_SCORE": FieldSpec("REQUIRED_SCORE", int, min_value=0, max_value=6),
    "REQUIRE_NO_NEW_EXTREME_5BARS": FieldSpec("REQUIRE_NO_NEW_EXTREME_5BARS", bool),
    "POINT_SIZE": FieldSpec("POINT_SIZE", float, min_value=0.000001, max_value=10.0),
    "MAX_SPREAD_POINTS": FieldSpec("MAX_SPREAD_POINTS", float, min_value=0.0, max_value=100_000.0),
    "ATR_MIN_POINTS": FieldSpec("ATR_MIN_POINTS", float, min_value=0.0, max_value=100_000.0),
    "STOP_MODE": FieldSpec("STOP_MODE", str, choices=("fixed", "atr")),
    "ATR_SL_MULTIPLIER": FieldSpec("ATR_SL_MULTIPLIER", float, min_value=0.1, max_value=20.0),
    "ATR_TP_MULTIPLIER": FieldSpec("ATR_TP_MULTIPLIER", float, min_value=0.1, max_value=20.0),
    "BROKER_MIN_STOP_POINTS": FieldSpec("BROKER_MIN_STOP_POINTS", int, min_value=0, max_value=100_000),
    "ENTRY_COOLDOWN_SECONDS": FieldSpec("ENTRY_COOLDOWN_SECONDS", int, min_value=0, max_value=86_400),
    "MAX_TRADES_PER_HOUR": FieldSpec("MAX_TRADES_PER_HOUR", int, min_value=0, max_value=1000),
    "MAX_TRADES_PER_DAY": FieldSpec("MAX_TRADES_PER_DAY", int, min_value=0, max_value=10_000),
    "MAX_DAILY_LOSS_PERCENT": FieldSpec("MAX_DAILY_LOSS_PERCENT", float, min_value=0.0, max_value=100.0),
    "LOSS_STREAK_THRESHOLD": FieldSpec("LOSS_STREAK_THRESHOLD", int, min_value=1, max_value=20),
    "COOLDOWN_AFTER_LOSSES_MINUTES": FieldSpec("COOLDOWN_AFTER_LOSSES_MINUTES", int, min_value=0, max_value=1440),
    "H1_EMA_FAST_PERIOD": FieldSpec("H1_EMA_FAST_PERIOD", int, min_value=1, max_value=500),
    "H1_EMA_SLOW_PERIOD": FieldSpec("H1_EMA_SLOW_PERIOD", int, min_value=2, max_value=1000),
    "H1_MIN_BARS": FieldSpec("H1_MIN_BARS", int, min_value=1, max_value=500),
    "PULLBACK_LOOKBACK_BARS": FieldSpec("PULLBACK_LOOKBACK_BARS", int, min_value=1, max_value=200),
    "PULLBACK_MIN_EXTENSION_ATR": FieldSpec("PULLBACK_MIN_EXTENSION_ATR", float, min_value=0.0, max_value=20.0),
    "PULLBACK_MAX_DISTANCE_ATR": FieldSpec("PULLBACK_MAX_DISTANCE_ATR", float, min_value=0.0, max_value=20.0),
    "SAME_DIRECTION_MIN_BARS": FieldSpec("SAME_DIRECTION_MIN_BARS", int, min_value=0, max_value=1000),
    "REENTRY_MIN_ATR_MULT": FieldSpec("REENTRY_MIN_ATR_MULT", float, min_value=0.0, max_value=20.0),
    "ENTRY_STRICTNESS": FieldSpec("ENTRY_STRICTNESS", str, choices=tuple(ENTRY_STRICTNESS_PRESETS)),
    "ENABLE_ORDERS": FieldSpec("ENABLE_ORDERS", bool),
    "DEMO_ONLY": FieldSpec("DEMO_ONLY", bool),
    "DISCORD_ENABLED": FieldSpec("DISCORD_ENABLED", bool),
    "DISCORD_WEBHOOK_URL": FieldSpec("DISCORD_WEBHOOK_URL", str),
    "DISCORD_NOTIFY_ON_TRADE": FieldSpec("DISCORD_NOTIFY_ON_TRADE", bool),
    "DISCORD_NOTIFY_ON_ERROR": FieldSpec("DISCORD_NOTIFY_ON_ERROR", bool),
    "DISCORD_NOTIFY_DAILY_SUMMARY": FieldSpec("DISCORD_NOTIFY_DAILY_SUMMARY", bool),
    "BOT_RUN_STATE": FieldSpec("BOT_RUN_STATE", str, choices=BOT_RUN_STATE_CHOICES),
    "AI_ENGINE": FieldSpec("AI_ENGINE", str, choices=AI_ENGINE_CHOICES),
    "ENABLED_SYMBOLS": FieldSpec("ENABLED_SYMBOLS", list, choices=AVAILABLE_SYMBOLS),
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
    if spec.type is list:
        if not isinstance(raw_value, list) or not all(isinstance(v, str) for v in raw_value):
            raise TypeError("文字列のリストである必要があります")
        return list(raw_value)
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

        if spec.choices is not None and spec.type is list:
            invalid = [v for v in value if v not in spec.choices]
            if invalid:
                errors[key] = (
                    f"{key}に無効な値が含まれています: {', '.join(invalid)}"
                    f"(選べるのは{', '.join(spec.choices)})"
                )
                continue
        elif spec.choices is not None and value not in spec.choices:
            errors[key] = f"{key}は次のいずれかを指定してください: {', '.join(spec.choices)}"
            continue

        if spec.min_value is not None and value < spec.min_value:
            errors[key] = f"{key}は{spec.min_value}以上である必要があります"
            continue
        if spec.max_value is not None and value > spec.max_value:
            errors[key] = f"{key}は{spec.max_value}以下である必要があります"
            continue

        cleaned[key] = value

    # Entry Strictnessのプリセットが指定され、対応するキーが明示的には
    # 送られてこなかった場合、プリセットの値で補う(payloadに同じキーが
    # 明示的に含まれていればそちらを優先。setdefault()のため)。
    if "ENTRY_STRICTNESS" in cleaned:
        preset = ENTRY_STRICTNESS_PRESETS[cleaned["ENTRY_STRICTNESS"]]
        for key, value in preset.items():
            cleaned.setdefault(key, value)

    # RSI/EMAの相互関係チェック。cleanedに無い側は現在の実効値(config.py)を使う。
    if "RSI_OVERBOUGHT" in cleaned or "RSI_OVERSOLD" in cleaned:
        overbought = cleaned.get("RSI_OVERBOUGHT", config.RSI_OVERBOUGHT)
        oversold = cleaned.get("RSI_OVERSOLD", config.RSI_OVERSOLD)
        if overbought <= oversold:
            errors["RSI_OVERBOUGHT"] = "RSI_OVERBOUGHTはRSI_OVERSOLDより大きい値にしてください"
            cleaned.pop("RSI_OVERBOUGHT", None)
            cleaned.pop("RSI_OVERSOLD", None)

    if "RSI_BUY_MIN" in cleaned or "RSI_BUY_MAX" in cleaned:
        buy_min = cleaned.get("RSI_BUY_MIN", config.RSI_BUY_MIN)
        buy_max = cleaned.get("RSI_BUY_MAX", config.RSI_BUY_MAX)
        if buy_min >= buy_max:
            errors["RSI_BUY_MIN"] = "RSI_BUY_MINはRSI_BUY_MAXより小さい値にしてください"
            cleaned.pop("RSI_BUY_MIN", None)
            cleaned.pop("RSI_BUY_MAX", None)

    if "RSI_SELL_MIN" in cleaned or "RSI_SELL_MAX" in cleaned:
        sell_min = cleaned.get("RSI_SELL_MIN", config.RSI_SELL_MIN)
        sell_max = cleaned.get("RSI_SELL_MAX", config.RSI_SELL_MAX)
        if sell_min >= sell_max:
            errors["RSI_SELL_MIN"] = "RSI_SELL_MINはRSI_SELL_MAXより小さい値にしてください"
            cleaned.pop("RSI_SELL_MIN", None)
            cleaned.pop("RSI_SELL_MAX", None)

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
