"""MetaTrader5ターミナルとの連携を担当するクライアント。

MT5への接続・切断、最新ティックの取得、ローソク足データの取得を提供する。
呼び出し側(main.py等)はこのクラスを経由してのみMT5 APIに触れる想定とし、
将来ブローカーAPIを追加/差し替える場合もこのファイルの変更で完結させる。

注意: `MetaTrader5` パッケージはWindows上で稼働するMT5ターミナルが
必要なため、Windows以外の環境ではimportに失敗する。その場合でも
このモジュール自体のimportは失敗させず、実際にMT5機能を使おうとした
タイミングで分かりやすいエラーを送出する。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:  # Windows以外の開発環境でも import 自体は失敗させない
    mt5 = None

import config

logger = logging.getLogger("mt5_ai_trader")

# mt5.initialize()がconfig.MT5_INIT_TIMEOUT_MSを無視して固まった場合に備え、
# その秒数を超えても戻ってこなければ強制的にタイムアウト扱いにするための
# 追加バッファ(秒)。
_INIT_WATCHDOG_BUFFER_SECONDS = 5

# config.TIMEFRAME (文字列) と MetaTrader5 モジュールの定数名の対応表。
# 新しい時間足を追加したい場合はここに1行足すだけでよい。
TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


class MT5ConnectionError(RuntimeError):
    """MT5への接続・初期化・データ取得に失敗した場合に送出する。"""


@dataclass
class Tick:
    symbol: str
    bid: float
    ask: float
    time: datetime


class MT5Client:
    """MT5ターミナルとの接続とデータ取得をカプセル化するクライアント。"""

    def __init__(self) -> None:
        self._connected = False

    def connect(self, timeout_ms: int | None = None) -> None:
        """MT5ターミナルに接続する。失敗した場合はMT5ConnectionErrorを送出する。

        mt5.initialize()自体にtimeout(ミリ秒)を渡すことに加え、万一その
        timeoutが効かずに呼び出しが返ってこないケースに備えて、別スレッドで
        呼び出した上でjoin()にハードタイムアウトを設定している。これにより
        本メソッドは(timeout_ms/1000 + バッファ秒)を超えて固まることがない。
        """
        if mt5 is None:
            raise MT5ConnectionError(
                "MetaTrader5パッケージが利用できません。Windows環境でMT5ターミナルを"
                "インストールし、'pip install MetaTrader5' を実行してください。"
            )

        timeout_ms = timeout_ms if timeout_ms is not None else config.MT5_INIT_TIMEOUT_MS

        path_display = config.MT5_TERMINAL_PATH or "(未指定/自動検出に依存)"
        if config.MT5_TERMINAL_PATH:
            path_exists = Path(config.MT5_TERMINAL_PATH).exists()
            if not path_exists:
                logger.warning(
                    "MT5_PATH='%s' が見つかりません。パスの誤りの可能性があります。",
                    config.MT5_TERMINAL_PATH,
                )
        else:
            path_exists = None

        logger.info(
            "MT5接続を開始します: path=%s (存在=%s) login=%s server=%s timeout_ms=%s",
            path_display,
            path_exists,
            config.MT5_LOGIN or "(未設定)",
            config.MT5_SERVER or "(未設定)",
            timeout_ms,
        )

        init_kwargs: dict = {"timeout": timeout_ms}
        if config.MT5_TERMINAL_PATH:
            init_kwargs["path"] = config.MT5_TERMINAL_PATH
        if config.MT5_LOGIN and config.MT5_PASSWORD and config.MT5_SERVER:
            init_kwargs["login"] = config.MT5_LOGIN
            init_kwargs["password"] = config.MT5_PASSWORD
            init_kwargs["server"] = config.MT5_SERVER

        logger.debug("mt5.initialize()を呼び出します kwargs=%s", {**init_kwargs, "password": "***" if "password" in init_kwargs else None})

        result: dict = {}

        def _call_initialize() -> None:
            result["ok"] = mt5.initialize(**init_kwargs)

        thread = threading.Thread(target=_call_initialize, daemon=True)
        started_at = time.monotonic()
        thread.start()
        thread.join(timeout=(timeout_ms / 1000) + _INIT_WATCHDOG_BUFFER_SECONDS)
        elapsed = time.monotonic() - started_at

        if thread.is_alive():
            logger.error(
                "mt5.initialize()が%.1f秒経過しても応答しません(タイムアウト)。"
                "MT5ターミナルが起動・ログイン済みか、MT5_PATH/MT5_SERVERが正しいか確認してください。",
                elapsed,
            )
            raise MT5ConnectionError(
                f"mt5.initialize()がタイムアウトしました({elapsed:.1f}秒応答なし)"
            )

        ok = result.get("ok", False)
        logger.info("mt5.initialize()が%.1f秒で返りました result=%s", elapsed, ok)

        if not ok:
            error = mt5.last_error()
            logger.error("MT5の初期化に失敗しました: last_error=%s", error)
            raise MT5ConnectionError(f"MT5の初期化に失敗しました: {error}")

        self._connected = True
        logger.info("MT5への接続に成功しました")

    def disconnect(self) -> None:
        """MT5ターミナルとの接続を閉じる。未接続の場合は何もしない。"""
        if mt5 is not None and self._connected:
            mt5.shutdown()
            self._connected = False
            logger.info("MT5との接続をshutdownしました")

    def get_latest_tick(self, symbol: str) -> Tick:
        """指定シンボルの最新Bid/Askを取得する。"""
        self._ensure_connected()
        logger.debug("symbol=%s のティック取得を開始します", symbol)

        if not mt5.symbol_select(symbol, True):
            raise MT5ConnectionError(f"シンボル '{symbol}' の選択に失敗しました")

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5ConnectionError(
                f"'{symbol}' のティック取得に失敗しました: {mt5.last_error()}"
            )

        logger.debug("symbol=%s tick取得完了 bid=%s ask=%s", symbol, tick.bid, tick.ask)
        return Tick(
            symbol=symbol,
            bid=tick.bid,
            ask=tick.ask,
            time=datetime.fromtimestamp(tick.time),
        )

    def get_candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        """直近count本のローソク足を取得し、DataFrameで返す。

        列: time, open, high, low, close, tick_volume, spread, real_volume
        """
        self._ensure_connected()
        tf_constant = self._resolve_timeframe(timeframe)
        logger.debug("symbol=%s timeframe=%s count=%s のローソク足取得を開始します", symbol, timeframe, count)

        rates = mt5.copy_rates_from_pos(symbol, tf_constant, 0, count)
        if rates is None or len(rates) == 0:
            raise MT5ConnectionError(
                f"'{symbol}' のローソク足取得に失敗しました: {mt5.last_error()}"
            )

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        logger.debug("ローソク足取得完了 件数=%s", len(df))
        return df

    def _resolve_timeframe(self, timeframe: str):
        attr_name = TIMEFRAME_MAP.get(timeframe.upper())
        if attr_name is None or not hasattr(mt5, attr_name):
            supported = ", ".join(TIMEFRAME_MAP.keys())
            raise MT5ConnectionError(
                f"未対応の時間足です: '{timeframe}' (対応値: {supported})"
            )
        return getattr(mt5, attr_name)

    def _ensure_connected(self) -> None:
        if mt5 is None or not self._connected:
            raise MT5ConnectionError(
                "MT5に接続されていません。先にconnect()を呼び出してください。"
            )

    def __enter__(self) -> "MT5Client":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()
