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

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:  # Windows以外の開発環境でも import 自体は失敗させない
    mt5 = None

import config

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

    def connect(self) -> None:
        """MT5ターミナルに接続する。失敗した場合はMT5ConnectionErrorを送出する。"""
        if mt5 is None:
            raise MT5ConnectionError(
                "MetaTrader5パッケージが利用できません。Windows環境でMT5ターミナルを"
                "インストールし、'pip install MetaTrader5' を実行してください。"
            )

        init_kwargs: dict = {}
        if config.MT5_TERMINAL_PATH:
            init_kwargs["path"] = config.MT5_TERMINAL_PATH
        if config.MT5_LOGIN and config.MT5_PASSWORD and config.MT5_SERVER:
            init_kwargs["login"] = config.MT5_LOGIN
            init_kwargs["password"] = config.MT5_PASSWORD
            init_kwargs["server"] = config.MT5_SERVER

        if not mt5.initialize(**init_kwargs):
            raise MT5ConnectionError(f"MT5の初期化に失敗しました: {mt5.last_error()}")

        self._connected = True

    def disconnect(self) -> None:
        """MT5ターミナルとの接続を閉じる。未接続の場合は何もしない。"""
        if mt5 is not None and self._connected:
            mt5.shutdown()
            self._connected = False

    def get_latest_tick(self, symbol: str) -> Tick:
        """指定シンボルの最新Bid/Askを取得する。"""
        self._ensure_connected()

        if not mt5.symbol_select(symbol, True):
            raise MT5ConnectionError(f"シンボル '{symbol}' の選択に失敗しました")

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5ConnectionError(
                f"'{symbol}' のティック取得に失敗しました: {mt5.last_error()}"
            )

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

        rates = mt5.copy_rates_from_pos(symbol, tf_constant, 0, count)
        if rates is None or len(rates) == 0:
            raise MT5ConnectionError(
                f"'{symbol}' のローソク足取得に失敗しました: {mt5.last_error()}"
            )

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
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
