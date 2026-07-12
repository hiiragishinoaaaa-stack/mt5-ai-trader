"""アプリケーション全体の設定値。

MT5の接続情報やインジケーター・AIエンジンなどのパラメータを環境変数(.env)
から読み込む。値が未設定の場合はデフォルト値を使用する。

一部の売買設定(settings_schema.FIELDSを参照)は、.envに加えて
config.json でも上書きできる。config.json は Dashboard の Settings画面
(settings_server.py経由)から書き込まれることを想定した設定ファイルで、
.envとは異なりGit管理対象外・実行中に書き換え可能なもの。読み込み優先度は
「config.json > .env > コード上のデフォルト値」。

起動時に一度、load_config_json()が自動的に呼ばれる。実行中にconfig.jsonが
更新された場合に反映するには、main.pyが各サイクルの先頭で
load_config_json()を呼び直す(ファイルの更新日時が変わっていなければ
何もしない、軽量なチェック)。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# config.py自身がロガーを使うのはload_config_json()内のみ。setup_logger()が
# 呼ばれる前(起動直後のimport時)にも安全に使えるよう、標準のlogging APIを
# そのまま使う(ハンドラ未設定でも例外にはならず、通常は何も出力されないだけ)。
_logger = logging.getLogger("mt5_ai_trader")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _common_files_dir() -> Path:
    """MT5の共有フォルダ(FILE_COMMON)のパスを返す。

    MT5はFILE_COMMONフラグを付けたファイルを
    %APPDATA%\\MetaQuotes\\Terminal\\Common\\Files\\ に書き出す。この場所は
    ブローカーごとのターミナルインストール先やデータフォルダのハッシュ名に
    依存しないため、Windows環境では追加設定なしでEAとPythonが同じファイルを
    見つけられる。Windows以外(開発・テスト用)ではプロジェクト直下を使う。
    """
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files"
    return BASE_DIR


# --- EAブリッジ(ファイル連携)設定 ---
# MT5 Python API(MetaTrader5パッケージ)はIPC timeoutが解消できなかったため
# 使用しない。代わりにMT5上で動くEA(ea/ARTEMIS_Bridge.mq5)がJSONファイル
# 経由で価格データの提供と発注リクエストの実行を行う
# (詳細はmarket_feed.py / order_executor.pyを参照)。
_market_data_file_path_env = os.getenv("MARKET_DATA_FILE_PATH")
MARKET_DATA_FILE_PATH = (
    Path(_market_data_file_path_env)
    if _market_data_file_path_env
    else _common_files_dir() / "artemis_market_data.json"
)
# EAの書き込みが止まっている(MT5が落ちている等)ことを検知するための
# 許容遅延(秒)。EAのInpUpdateIntervalSecより十分大きい値にすること。
MARKET_DATA_MAX_STALENESS_SECONDS = _env_int("MARKET_DATA_MAX_STALENESS_SECONDS", 30)

# --- 口座情報・ポジション(Phase 3: Dashboardの残高/ポジション表示) ---
# EA(ea/ARTEMIS_Bridge.mq5)が書き出す残高・証拠金・保有ポジション一覧の
# JSONファイル(account_feed.py参照)。
_account_state_file_path_env = os.getenv("ACCOUNT_STATE_FILE_PATH")
ACCOUNT_STATE_FILE_PATH = (
    Path(_account_state_file_path_env)
    if _account_state_file_path_env
    else _common_files_dir() / "artemis_account_state.json"
)
ACCOUNT_STATE_MAX_STALENESS_SECONDS = _env_int("ACCOUNT_STATE_MAX_STALENESS_SECONDS", 30)

# --- 取引履歴(Phase 4: Dashboardの注文履歴/統計表示) ---
# EA(ea/ARTEMIS_Bridge.mq5、v4.00以降)が書き出す決済済み取引一覧のJSON
# ファイル(trade_history_feed.py参照)。
_trade_history_file_path_env = os.getenv("TRADE_HISTORY_FILE_PATH")
TRADE_HISTORY_FILE_PATH = (
    Path(_trade_history_file_path_env)
    if _trade_history_file_path_env
    else _common_files_dir() / "artemis_trade_history.json"
)
# EAのInpTradeHistoryIntervalSec(既定10秒)より十分大きい値にすること。
TRADE_HISTORY_MAX_STALENESS_SECONDS = _env_int("TRADE_HISTORY_MAX_STALENESS_SECONDS", 60)

# --- AI判断のリアルタイム表示(Phase 4: Dashboardのモック解消) ---
# main.pyが各サイクルの判断をここへ書き出し、Dashboardが表示する
# (MT5 EAを介さないPython内部のみのやり取りなので、Common\Filesは使わない)。
_ai_status_file_path_env = os.getenv("AI_STATUS_FILE_PATH")
AI_STATUS_FILE_PATH = Path(_ai_status_file_path_env) if _ai_status_file_path_env else BASE_DIR / "artemis_ai_status.json"
# LOOP_INTERVAL_SECONDSより十分大きい値にすること(既定60秒ループに対し120秒)。
AI_STATUS_MAX_STALENESS_SECONDS = _env_int("AI_STATUS_MAX_STALENESS_SECONDS", 120)

# --- 発注(Phase2) ---
# ENABLE_ORDERSとDEMO_ONLYの両方が明示的にtrueの場合のみ発注リクエストを
# 書き出す(既定はどちらもfalse)。ENABLE_ORDERSは「発注そのものを行うか」、
# DEMO_ONLYは「対象口座がデモであること」を表す独立した設定で、Dashboardの
# Settings画面では別々のトグルとして扱う。EA側でも別途、口座が本当に
# デモかどうかを再検証する(多重の安全装置)。
ENABLE_ORDERS = _env_bool("ENABLE_ORDERS", False)
DEMO_ONLY = _env_bool("DEMO_ONLY", False)
ORDER_VOLUME = _env_float("ORDER_VOLUME", 0.01)
# SL/TPは価格ではなく「ポイント数」で指定し、EA側で実際の価格に変換する
# (シンボルのpoint/桁数はEA側の方が正確に把握できるため)。0以下ならSL/TPなし。
SL_POINTS = _env_int("SL_POINTS", 200)
TP_POINTS = _env_int("TP_POINTS", 400)
_order_request_file_path_env = os.getenv("ORDER_REQUEST_FILE_PATH")
ORDER_REQUEST_FILE_PATH = (
    Path(_order_request_file_path_env)
    if _order_request_file_path_env
    else _common_files_dir() / "artemis_order_request.json"
)
_order_result_file_path_env = os.getenv("ORDER_RESULT_FILE_PATH")
ORDER_RESULT_FILE_PATH = (
    Path(_order_result_file_path_env)
    if _order_result_file_path_env
    else _common_files_dir() / "artemis_order_result.json"
)
# EAが発注リクエストを処理し、結果ファイルを書き出すまでの最大待ち時間(秒)。
ORDER_RESULT_WAIT_SECONDS = _env_float("ORDER_RESULT_WAIT_SECONDS", 10.0)

# --- 発注テスト用モード ---
# 通常のAI判断(BUY/SELL/WAIT)を上書きして強制する。空欄なら無効で、既存の
# AI判断ロジックのまま動作する。値の妥当性チェックとDEMO_ONLYとの組み合わせは
# main.py側で行う(ここでは生の文字列を読むだけ)。
FORCE_SIGNAL = os.getenv("FORCE_SIGNAL", "").strip().upper()
# trueの場合、起動後1サイクルだけ実行して終了する(--once/ループ設定より優先)。
# FORCE_SIGNALと組み合わせて「条件を待たずに1回だけ発注テストする」用途を想定。
TEST_ORDER_ONCE = _env_bool("TEST_ORDER_ONCE", False)

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
# エントリーの厳しさのプリセット名(conservative/balanced/aggressive)。
# 数値としての効果はRSI_OVERBOUGHT/RSI_OVERSOLDに反映される
# (settings_schema.ENTRY_STRICTNESS_PRESETSを参照)。この値自体は
# ai_engine.pyの判断ロジックには使われず、Dashboard表示用の記録値。
ENTRY_STRICTNESS = os.getenv("ENTRY_STRICTNESS", "balanced")

# --- AI判断エンジン ---
# rule_based | openai | claude。openai/claudeは実際にAPIを呼び出すため、
# 利用ごとに料金が発生する(LOOP_INTERVAL_SECONDSの間隔で毎サイクル呼ばれる)。
# 詳細はopenai_engine.py / claude_engine.py、README.mdの
# 「AI判断エンジン: OpenAI/Claude連携(Phase 7)」を参照。
AI_ENGINE = os.getenv("AI_ENGINE", "rule_based")
# APIキーはセキュリティ上の理由でDashboard(settings_schema.FIELDS)には含めず、
# .envでのみ設定する(settings_server.pyのGET /api/settingsで外部に
# 露出させないため)。未設定の場合、該当エンジンは毎回WAITにフォールバックする。
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
AI_ENGINE_TIMEOUT_SECONDS = _env_int("AI_ENGINE_TIMEOUT_SECONDS", 20)

# --- 実行制御 ---
LOOP_INTERVAL_SECONDS = _env_int("LOOP_INTERVAL_SECONDS", 60)

# --- ログ ---
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "trades.log"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# --- ボットの起動/停止(Phase 5: DashboardのSTART/STOP/EMERGENCY STOP) ---
# RUNNING以外の場合、main.pyは判断・発注をスキップする(プロセス自体は
# systemdサービスとして動き続ける。詳細はmain.py run_once()を参照)。
BOT_RUN_STATE = os.getenv("BOT_RUN_STATE", "RUNNING")

# --- Discord通知(Phase 4: 取引ごとの通知) ---
# DISCORD_ENABLEDとWebhook URLの両方が設定されている場合のみ通知を送信する。
DISCORD_ENABLED = _env_bool("DISCORD_ENABLED", False)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_NOTIFY_ON_TRADE = _env_bool("DISCORD_NOTIFY_ON_TRADE", True)
DISCORD_NOTIFY_ON_ERROR = _env_bool("DISCORD_NOTIFY_ON_ERROR", True)

# --- 日次サマリー通知(Phase 6) ---
# DISCORD_ENABLEDとこの両方がtrueの場合、1日1回(DAILY_SUMMARY_HOURで
# 指定した時刻(UTC・VPSのローカル時刻)以降の最初のサイクル)、その日
# (UTC暦日)の損益サマリーをDiscordへ送信する。詳細はdaily_summary.pyを参照。
DISCORD_NOTIFY_DAILY_SUMMARY = _env_bool("DISCORD_NOTIFY_DAILY_SUMMARY", False)
DAILY_SUMMARY_HOUR = _env_int("DAILY_SUMMARY_HOUR", 13)  # 既定13時(UTC) = 22時(JST)
_daily_summary_state_file_path_env = os.getenv("DAILY_SUMMARY_STATE_FILE_PATH")
DAILY_SUMMARY_STATE_FILE_PATH = (
    Path(_daily_summary_state_file_path_env)
    if _daily_summary_state_file_path_env
    else BASE_DIR / "artemis_daily_summary_state.json"
)

# --- Dashboard設定API(settings_server.py) ---
_config_json_path_env = os.getenv("CONFIG_JSON_PATH")
CONFIG_JSON_PATH = Path(_config_json_path_env) if _config_json_path_env else BASE_DIR / "config.json"
# Dashboard(スマホ含む)からアクセスできるよう既定で全インターフェースに
# 待受する。ローカルの信頼できるネットワーク以外には公開しないこと
# (settings_server.pyには認証機能が無い。SETTINGS_API_TOKENで簡易保護は可能)。
SETTINGS_SERVER_HOST = os.getenv("SETTINGS_SERVER_HOST", "0.0.0.0")
SETTINGS_SERVER_PORT = _env_int("SETTINGS_SERVER_PORT", 8787)
# 設定した場合、settings_server.pyへのリクエストに
# `Authorization: Bearer <token>` ヘッダーが必須になる(任意の追加防御)。
SETTINGS_API_TOKEN = os.getenv("SETTINGS_API_TOKEN", "")


def _apply_overrides(overrides: dict) -> None:
    """overridesの中身をこのモジュールの対応する属性へ反映する。

    settings_schema.FIELDSに定義されたキーのみを対象とする。値の型が
    想定と異なる場合はそのキーだけスキップし、他の項目には影響しない
    (config.jsonが手動編集で壊れていてもBOT全体を落とさないため)。
    循環import回避のため、settings_schemaはここで遅延importする
    (settings_schema.py 側がconfig.pyをimportしているため)。
    """
    import settings_schema  # 遅延import(循環import回避)

    module = sys.modules[__name__]
    for key, value in overrides.items():
        spec = settings_schema.FIELDS.get(key)
        if spec is None:
            continue
        try:
            coerced = settings_schema.coerce(value, spec)
        except (TypeError, ValueError):
            _logger.warning(
                "config: config.jsonの%sの値(%r)が不正な型のため無視します", key, value
            )
            continue
        setattr(module, key, coerced)


_config_json_mtime: float | None = None


def load_config_json(*, force: bool = False) -> bool:
    """config.jsonが存在すれば読み込み、対応するモジュール属性を上書きする。

    起動時に自動で1回呼ばれる(本ファイル末尾)ほか、main.pyが実行中の各
    サイクルでも呼び出し、Dashboardからの設定変更を反映する。ファイルの
    更新日時が前回と変わっていなければ何もしない(force=Trueで強制再読込)。
    戻り値: 実際に(再)読込を行ったかどうか。
    """
    global _config_json_mtime

    if not CONFIG_JSON_PATH.exists():
        return False

    try:
        mtime = CONFIG_JSON_PATH.stat().st_mtime
    except OSError:
        return False

    if not force and mtime == _config_json_mtime:
        return False

    try:
        with CONFIG_JSON_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        _logger.warning("config: config.jsonの読み込みに失敗しました: %s", exc)
        return False

    if not isinstance(raw, dict):
        _logger.warning("config: config.jsonの中身がオブジェクトではありません(無視します)")
        return False

    _apply_overrides(raw)
    _config_json_mtime = mtime
    return True


# 起動時に1回、既存のconfig.jsonがあれば読み込んで反映しておく。
load_config_json(force=True)
