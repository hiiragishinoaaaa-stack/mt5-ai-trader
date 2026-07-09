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


def _default_market_data_path() -> Path:
    """EA(ARTEMIS_MarketFeed.mq5)が書き出すJSONファイルの既定パスを返す。

    MT5はFILE_COMMONフラグを付けたファイルを
    %APPDATA%\\MetaQuotes\\Terminal\\Common\\Files\\ に書き出す。この場所は
    ブローカーごとのターミナルインストール先やデータフォルダのハッシュ名に
    依存しないため、Windows環境では追加設定なしでEAとPythonが同じファイルを
    見つけられる。Windows以外(開発・テスト用)ではプロジェクト直下を使う。
    """
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files" / "artemis_market_data.json"
    return BASE_DIR / "artemis_market_data.json"


# --- EAブリッジ(ファイル連携)設定 ---
# MT5 Python API(MetaTrader5パッケージ)はIPC timeoutが解消できなかったため
# 使用しない。代わりにMT5上で動くEAがJSONファイルへ価格データを書き出し、
# Pythonはそのファイルを読むだけの構成にしている(詳細はmarket_feed.py参照)。
_market_data_file_path_env = os.getenv("MARKET_DATA_FILE_PATH")
MARKET_DATA_FILE_PATH = (
    Path(_market_data_file_path_env) if _market_data_file_path_env else _default_market_data_path()
)
# EAの書き込みが止まっている(MT5が落ちている等)ことを検知するための
# 許容遅延(秒)。EAのInpUpdateIntervalSecより十分大きい値にすること。
MARKET_DATA_MAX_STALENESS_SECONDS = _env_int("MARKET_DATA_MAX_STALENESS_SECONDS", 30)

# --- 取引対象 ---
# EA側のInpSymbol / InpTimeframeと必ず一致させること(market_feed.pyが検証する)。
SYMBOL = os.getenv("SYMBOL", "USDJPY")
TIMEFRAME = os.getenv("TIMEFRAME", "M15")
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
