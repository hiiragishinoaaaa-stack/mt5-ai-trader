"""アプリケーション全体の設定値。

MT5の接続情報やインジケーター・AIエンジンなどのパラメータを環境変数(.env)
から読み込む。値が未設定の場合はデフォルト値を使用する。
設定を変更したい場合はこのファイル、または .env を編集すればよく、
他のモジュールを直接触る必要はない。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


# --- MT5接続情報 ---
MT5_LOGIN = _env_int("MT5_LOGIN", 0) or None
MT5_PASSWORD = os.getenv("MT5_PASSWORD")
MT5_SERVER = os.getenv("MT5_SERVER")
MT5_TERMINAL_PATH = os.getenv("MT5_PATH")  # terminal64.exe のパス(任意)
# mt5.initialize()に渡すタイムアウト(ミリ秒)。ターミナルが応答しない場合に
# 無限に固まらないようにするためのガード。
MT5_INIT_TIMEOUT_MS = _env_int("MT5_INIT_TIMEOUT_MS", 10000)

# --- 取引対象 ---
SYMBOL = os.getenv("SYMBOL", "USDJPY")
TIMEFRAME = os.getenv("TIMEFRAME", "M15")  # mt5_client.TIMEFRAME_MAP のキーに対応
BARS_COUNT = _env_int("BARS_COUNT", 100)

# --- インジケーター設定 ---
EMA_FAST_PERIOD = _env_int("EMA_FAST_PERIOD", 9)
EMA_SLOW_PERIOD = _env_int("EMA_SLOW_PERIOD", 21)
RSI_PERIOD = _env_int("RSI_PERIOD", 14)
RSI_OVERBOUGHT = _env_float("RSI_OVERBOUGHT", 70.0)
RSI_OVERSOLD = _env_float("RSI_OVERSOLD", 30.0)
MACD_FAST_PERIOD = _env_int("MACD_FAST_PERIOD", 12)
MACD_SLOW_PERIOD = _env_int("MACD_SLOW_PERIOD", 26)
MACD_SIGNAL_PERIOD = _env_int("MACD_SIGNAL_PERIOD", 9)

# --- AI判断エンジン ---
# "rule_based" が現在の唯一の実装。"openai" / "claude" は将来の拡張ポイント。
AI_ENGINE = os.getenv("AI_ENGINE", "rule_based")

# --- 実行制御 ---
LOOP_INTERVAL_SECONDS = _env_int("LOOP_INTERVAL_SECONDS", 60)

# --- ログ ---
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "trades.log"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
