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
# 同じ銘柄で同時に保有できるARTEMIS自身のポジション数の上限。EA側が実際の
# カウント・強制(超過分の発注拒否)を行う(要EA v4.01以降)。旧バージョンの
# EAはこの値を無視し、常に上限1として動作する。
MAX_CONCURRENT_POSITIONS = _env_int("MAX_CONCURRENT_POSITIONS", 1)
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

# --- 手動決済(Phase 10: DashboardからのCLOSEボタン) ---
# 発注リクエストとは別のファイルを使う(main.pyのAI判断ループが送出する
# 通常の発注リクエストと、Dashboardからの手動決済リクエストが同時に
# 発生した場合でもファイルが衝突しないようにするため)。要EA v4.03以降。
_close_request_file_path_env = os.getenv("CLOSE_REQUEST_FILE_PATH")
CLOSE_REQUEST_FILE_PATH = (
    Path(_close_request_file_path_env)
    if _close_request_file_path_env
    else _common_files_dir() / "artemis_close_request.json"
)
_close_result_file_path_env = os.getenv("CLOSE_RESULT_FILE_PATH")
CLOSE_RESULT_FILE_PATH = (
    Path(_close_result_file_path_env)
    if _close_result_file_path_env
    else _common_files_dir() / "artemis_close_result.json"
)

# --- EA設定の動的反映(Phase 11: TIMEFRAME変更をPCなしで反映) ---
# main.pyが毎サイクル、現在のconfig.TIMEFRAMEをこのファイルへ書き出す
# (ea_config_writer.py参照)。EA(v4.04以降)がOnTimer()の度にこのファイルを
# 読み込み、実際にCopyRatesへ渡す時間軸を動的に切り替える。これにより、
# DashboardでTIMEFRAMEを変更するだけでMT5側の再コンパイル・GUI操作なしに
# 反映されるようになる(要EA v4.04以降。それより前のEAはInpTimeframeの
# コンパイル時の値のまま固定)。
_ea_config_file_path_env = os.getenv("EA_CONFIG_FILE_PATH")
EA_CONFIG_FILE_PATH = (
    Path(_ea_config_file_path_env)
    if _ea_config_file_path_env
    else _common_files_dir() / "artemis_ea_config.json"
)

# --- 複数銘柄対応(Phase 12: DashboardからのON/OFF切り替え) ---
# main.pyはconfig.ENABLED_SYMBOLSに含まれる銘柄それぞれについて、価格取得
# →AI判断→発注を独立に行う(1銘柄=1EAインスタンスがMT5側に必要。EA自体は
# 銘柄をコード内にハードコードしていないため、同じEA(ARTEMIS_Bridge.mq5)を
# 銘柄ごとに別チャートへ追加し、入力パラメータ(InpSymbol・各種ファイル名)
# だけを変えて設置する。EA側の再コンパイルは不要)。
#
# 選べる銘柄の一覧はsettings_schema.AVAILABLE_SYMBOLSが唯一の正
# (Dashboardのトグル一覧・バリデーション両方がここを参照する)。
#
# 既定値はSYMBOL(プライマリ銘柄)定義の直後で設定する(下記「取引対象」
# セクション参照。ここではまだSYMBOLが定義されていないため代入できない)。
# config.json経由でDashboardから変更できる(settings_schema.FIELDSの
# ENABLED_SYMBOLS参照)。


def _for_symbol(path: Path, symbol: str) -> Path:
    """ファイルブリッジのパスを銘柄ごとに振り分ける。

    プライマリ銘柄(config.SYMBOL、既にVPSで稼働中のEAインスタンスが使っている
    ファイル名)はそのまま返す(後方互換、追加のPC作業なしで動き続ける)。
    それ以外の銘柄は拡張子の前に "_(小文字の銘柄名)" を挿入した別ファイル名を
    返す。これにより、銘柄ごとに別々のEAインスタンス(別チャートに追加した
    もの)がお互いのリクエスト/結果ファイルを衝突させずに使える。
    """
    if symbol == SYMBOL:
        return path
    return path.with_name(f"{path.stem}_{symbol.lower()}{path.suffix}")


def market_data_file_path(symbol: str) -> Path:
    return _for_symbol(MARKET_DATA_FILE_PATH, symbol)


def order_request_file_path(symbol: str) -> Path:
    return _for_symbol(ORDER_REQUEST_FILE_PATH, symbol)


def order_result_file_path(symbol: str) -> Path:
    return _for_symbol(ORDER_RESULT_FILE_PATH, symbol)


def close_request_file_path(symbol: str) -> Path:
    return _for_symbol(CLOSE_REQUEST_FILE_PATH, symbol)


def close_result_file_path(symbol: str) -> Path:
    return _for_symbol(CLOSE_RESULT_FILE_PATH, symbol)


def ea_config_file_path(symbol: str) -> Path:
    return _for_symbol(EA_CONFIG_FILE_PATH, symbol)


def ai_status_file_path(symbol: str) -> Path:
    return _for_symbol(AI_STATUS_FILE_PATH, symbol)


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
# 複数銘柄対応(Phase 12)の既定値。SYMBOL定義の直後でなければ参照できない
# ため、このタイミングで設定する(上の「複数銘柄対応」コメント参照)。
ENABLED_SYMBOLS: tuple[str, ...] | list[str] = (SYMBOL,)

# --- インジケーター設定 ---
EMA_FAST_PERIOD = _env_int("EMA_FAST_PERIOD", 9)
EMA_SLOW_PERIOD = _env_int("EMA_SLOW_PERIOD", 21)
RSI_PERIOD = _env_int("RSI_PERIOD", 14)
RSI_OVERBOUGHT = _env_float("RSI_OVERBOUGHT", 70.0)
RSI_OVERSOLD = _env_float("RSI_OVERSOLD", 30.0)
MACD_FAST_PERIOD = _env_int("MACD_FAST_PERIOD", 12)
MACD_SLOW_PERIOD = _env_int("MACD_SLOW_PERIOD", 26)
MACD_SIGNAL_PERIOD = _env_int("MACD_SIGNAL_PERIOD", 9)
ATR_PERIOD = _env_int("ATR_PERIOD", 14)

# --- エントリー条件のスコアリング方式(RuleBasedAIEngine) ---
# 「必須条件」(全て満たす必要がある)と「加点条件」(REQUIRED_SCORE点以上で
# エントリー候補)に分けて判断する。RSI_BUY_MIN/MAX・RSI_SELL_MIN/MAX・
# REQUIRED_SCORE・REQUIRE_NO_NEW_EXTREME_5BARSは、いずれもENTRY_STRICTNESS
# プリセット(settings_schema.ENTRY_STRICTNESS_PRESETS)経由で一括設定される
# ことを想定した値で、個別にも上書きできる。詳細はai_engine.RuleBasedAIEngine
# のdocstringを参照。
RSI_BUY_MIN = _env_float("RSI_BUY_MIN", 50.0)
RSI_BUY_MAX = _env_float("RSI_BUY_MAX", 65.0)
RSI_SELL_MIN = _env_float("RSI_SELL_MIN", 35.0)
RSI_SELL_MAX = _env_float("RSI_SELL_MAX", 50.0)
# 必須条件を満たした上で、加点条件(5つ、各1点)が何点以上ならエントリー
# 候補とするか。
REQUIRED_SCORE = _env_int("REQUIRED_SCORE", 3)
# 直近5本(最新を除く)の安値/高値を更新していないことを追加の必須条件に
# するかどうか(取引回数を大きく減らすため、conservativeプリセットのみtrue)。
REQUIRE_NO_NEW_EXTREME_5BARS = _env_bool("REQUIRE_NO_NEW_EXTREME_5BARS", False)
# ブローカーの1pointあたりの価格(例: USDJPYで3桁ブローカーなら0.001)。
# ATR(価格単位)をpoints単位のSL/TPへ変換するために使う。実際のブローカー
# の値と一致していないとSL/TP幅がずれるため、Dashboard Settingsで必ず
# 確認・調整すること。
POINT_SIZE = _env_float("POINT_SIZE", 0.001)
# 現在のスプレッド(EAが書き出す直近ローソク足のspread列、points単位)が
# この値を超える場合はエントリーしない。0以下で無効。
MAX_SPREAD_POINTS = _env_float("MAX_SPREAD_POINTS", 30.0)
# ATR(points換算)がこの値未満(値動きが小さすぎる)の場合はエントリーしない。
# 0以下で無効。
ATR_MIN_POINTS = _env_float("ATR_MIN_POINTS", 0.0)

# --- SL/TP方式(order_executor.py) ---
# fixed: 従来通りSL_POINTS/TP_POINTS固定。atr: ATR(14)×倍率で毎回動的に計算。
STOP_MODE = os.getenv("STOP_MODE", "fixed")
ATR_SL_MULTIPLIER = _env_float("ATR_SL_MULTIPLIER", 1.2)
ATR_TP_MULTIPLIER = _env_float("ATR_TP_MULTIPLIER", 1.8)
# ブローカーの最小ストップ距離(points)。ATRベースで計算したSL/TPがこれを
# 下回る場合はこの値まで引き上げる。0で補正なし(EA側は現在この検証を
# 行っていないため、値が小さすぎると発注がブローカーに拒否される可能性がある)。
BROKER_MIN_STOP_POINTS = _env_int("BROKER_MIN_STOP_POINTS", 0)

# --- エントリー頻度の制御・サーキットブレーカー(risk_manager.py) ---
# 同一銘柄で新規エントリーしてから次のエントリーまで最低これだけ間隔を空ける
# (秒)。0で無効。
ENTRY_COOLDOWN_SECONDS = _env_int("ENTRY_COOLDOWN_SECONDS", 0)
# 直近1時間/1日に新規オープンした回数がこれを超えたら新規エントリーを止める。
# 0で無効。
MAX_TRADES_PER_HOUR = _env_int("MAX_TRADES_PER_HOUR", 0)
MAX_TRADES_PER_DAY = _env_int("MAX_TRADES_PER_DAY", 0)
# その日(UTC日付)の決済済み損益の合計が、残高に対してこの%以上のマイナスに
# 達したら、その日は新規エントリーを止める。0以下で無効。
MAX_DAILY_LOSS_PERCENT = _env_float("MAX_DAILY_LOSS_PERCENT", 0.0)
# 直近LOSS_STREAK_THRESHOLD回連続で損切りになった場合、
# COOLDOWN_AFTER_LOSSES_MINUTES分だけ新規エントリーを止める。
# COOLDOWN_AFTER_LOSSES_MINUTES=0で無効。
LOSS_STREAK_THRESHOLD = _env_int("LOSS_STREAK_THRESHOLD", 3)
COOLDOWN_AFTER_LOSSES_MINUTES = _env_int("COOLDOWN_AFTER_LOSSES_MINUTES", 0)

# エントリーの厳しさのプリセット名(conservative/balanced/aggressive/active_m5)。
# 数値としての効果は上記のRSI_BUY_MIN/MAX等に反映される
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

# --- 決済通知(Phase 8) ---
# DISCORD_ENABLEDとDISCORD_NOTIFY_ON_TRADEの両方がtrueの場合、trade_history_feed.py
# (EAが書き出す決済済み取引一覧)を毎サイクル確認し、前回確認時より新しく
# 決済された取引があればDiscordへ通知する(close_notifier.py参照)。専用の
# ON/OFFは無く、発注時の通知と同じDISCORD_NOTIFY_ON_TRADEを共用する。
_close_notifier_state_file_path_env = os.getenv("CLOSE_NOTIFIER_STATE_FILE_PATH")
CLOSE_NOTIFIER_STATE_FILE_PATH = (
    Path(_close_notifier_state_file_path_env)
    if _close_notifier_state_file_path_env
    else BASE_DIR / "artemis_close_notifier_state.json"
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
