"""MetaTrader5ターミナルとの連携を担当するクライアント。

MT5への接続・ティック取得・ローソク足取得を提供する。呼び出し側(main.py等)
はこのクラスを経由してのみMT5 APIに触れる想定とし、将来ブローカーAPIを
追加/差し替える場合もこのファイルの変更で完結させる。

## なぜ別プロセスで実行するのか

`MetaTrader5`パッケージ(MetaQuotes製のC拡張)は、`mt5.initialize()`が
ターミナルとのIPC待機中にブロックした場合、Python側のGIL(Global
Interpreter Lock)を解放しないケースがあることを実運用で確認した。
その場合、別スレッドでタイムアウトを実装しても、インタプリタ全体が
固まってしまい検知・打ち切りができない。

そのためこのモジュールでは、接続からデータ取得・切断までを常に
`multiprocessing`の別プロセスで実行する。プロセスはOSレベルで
`terminate()`/`kill()`できるため、C拡張側がどれだけブロックしていても
確実に打ち切ることができる。

また、MT5のPython APIは接続状態をプロセスローカルに保持する(親プロセスと
子プロセスで状態を共有できない)ため、「接続」だけを分離することはできず、
「接続 → ティック取得 → ローソク足取得 → 切断」を1つの子プロセスの中で
完結させ、結果(プリミティブ型のみで構成したdict)をQueue経由で親プロセスに
返す設計にしている。

注意: `MetaTrader5` パッケージはWindows上で稼働するMT5ターミナルが
必要なため、Windows以外の環境ではimportに失敗する。その場合でも
このモジュール自体のimportは失敗させず、実際にMT5機能を使おうとした
タイミングで分かりやすいエラーを送出する。
"""
from __future__ import annotations

import logging
import multiprocessing
import queue as queue_module
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

# 子プロセスの強制終了(terminate)後、後片付け(join)を待つ最大秒数。
_TERMINATE_JOIN_TIMEOUT_SECONDS = 5
# 親プロセスがQueueをポーリングする間隔(秒)。短すぎるとCPUを無駄に消費し、
# 長すぎるとタイムアウト判定の精度が落ちるため、両者のバランスを取っている。
_POLL_INTERVAL_SECONDS = 0.5


class MT5ConnectionError(RuntimeError):
    """MT5への接続・初期化・データ取得に失敗した場合に送出する。"""


@dataclass
class Tick:
    symbol: str
    bid: float
    ask: float
    time: datetime


@dataclass
class MarketSnapshot:
    """1回分の取得で得られる価格データ一式。"""

    tick: Tick
    candles: pd.DataFrame


def _fetch_worker(result_queue: multiprocessing.Queue, mt5_kwargs: dict, symbol: str, timeframe: str, bars_count: int) -> None:
    """別プロセスで実行され、接続〜切断までを完結させるワーカー関数。

    MetaTrader5パッケージがない環境で誤って実行されないよう、呼び出し元の
    MT5Client.fetch_snapshot()側でも事前にmt5の有無を確認しているが、
    念のためここでも安全に失敗するようにしている。

    ログはこのプロセス内のloggerではなく、result_queueに乗せて親プロセスに
    渡し、親プロセス側の統一されたロガー(logs/trades.log)から出力する。
    """

    def _send_log(level: int, message: str) -> None:
        result_queue.put({"log": (level, message)})

    try:
        import MetaTrader5 as worker_mt5
    except ImportError:
        result_queue.put({"result": {"ok": False, "error": "MetaTrader5パッケージが利用できません"}})
        return

    masked_kwargs = {**mt5_kwargs, "password": "***" if "password" in mt5_kwargs else None}
    _send_log(logging.DEBUG, f"[子プロセス] mt5.initialize()を呼び出します kwargs={masked_kwargs}")

    started_at = time.monotonic()
    ok = worker_mt5.initialize(**mt5_kwargs)
    elapsed = time.monotonic() - started_at
    _send_log(logging.INFO, f"[子プロセス] mt5.initialize()が{elapsed:.1f}秒で返りました result={ok}")

    if not ok:
        error = worker_mt5.last_error()
        result_queue.put({"result": {"ok": False, "error": f"MT5の初期化に失敗しました: {error}"}})
        return

    try:
        if not worker_mt5.symbol_select(symbol, True):
            result_queue.put({"result": {"ok": False, "error": f"シンボル '{symbol}' の選択に失敗しました"}})
            return

        tick = worker_mt5.symbol_info_tick(symbol)
        if tick is None:
            result_queue.put(
                {"result": {"ok": False, "error": f"'{symbol}' のティック取得に失敗しました: {worker_mt5.last_error()}"}}
            )
            return
        _send_log(logging.DEBUG, f"[子プロセス] tick取得完了 bid={tick.bid} ask={tick.ask}")

        attr_name = TIMEFRAME_MAP.get(timeframe.upper())
        if attr_name is None or not hasattr(worker_mt5, attr_name):
            supported = ", ".join(TIMEFRAME_MAP.keys())
            result_queue.put(
                {"result": {"ok": False, "error": f"未対応の時間足です: '{timeframe}' (対応値: {supported})"}}
            )
            return

        rates = worker_mt5.copy_rates_from_pos(symbol, getattr(worker_mt5, attr_name), 0, bars_count)
        if rates is None or len(rates) == 0:
            result_queue.put(
                {"result": {"ok": False, "error": f"'{symbol}' のローソク足取得に失敗しました: {worker_mt5.last_error()}"}}
            )
            return
        _send_log(logging.DEBUG, f"[子プロセス] ローソク足取得完了 件数={len(rates)}")

        candles = [
            {
                "time": float(row["time"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "tick_volume": int(row["tick_volume"]),
                "spread": int(row["spread"]),
                "real_volume": int(row["real_volume"]),
            }
            for row in rates
        ]

        result_queue.put(
            {
                "result": {
                    "ok": True,
                    "tick": {
                        "symbol": symbol,
                        "bid": float(tick.bid),
                        "ask": float(tick.ask),
                        "time": float(tick.time),
                    },
                    "candles": candles,
                }
            }
        )
    finally:
        worker_mt5.shutdown()


class MT5Client:
    """MT5ターミナルとの接続とデータ取得をカプセル化するクライアント。

    内部状態を持たない(接続〜切断を毎回1つの子プロセスで完結させるため)。
    """

    def _build_init_kwargs(self, timeout_ms: int) -> dict:
        init_kwargs: dict = {"timeout": timeout_ms}
        if config.MT5_TERMINAL_PATH:
            init_kwargs["path"] = config.MT5_TERMINAL_PATH
        if config.MT5_LOGIN and config.MT5_PASSWORD and config.MT5_SERVER:
            init_kwargs["login"] = config.MT5_LOGIN
            init_kwargs["password"] = config.MT5_PASSWORD
            init_kwargs["server"] = config.MT5_SERVER
        return init_kwargs

    def fetch_snapshot(
        self,
        symbol: str,
        timeframe: str,
        bars_count: int,
        timeout_seconds: float | None = None,
    ) -> MarketSnapshot:
        """MT5への接続からティック・ローソク足取得までを別プロセスで実行する。

        timeout_seconds を超えても子プロセスが結果を返さない場合は
        強制終了(terminate/kill)し、MT5ConnectionErrorを送出する。
        """
        if mt5 is None:
            raise MT5ConnectionError(
                "MetaTrader5パッケージが利用できません。Windows環境でMT5ターミナルを"
                "インストールし、'pip install MetaTrader5' を実行してください。"
            )

        timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else config.MT5_FETCH_TIMEOUT_SECONDS
        )

        path_display = config.MT5_TERMINAL_PATH or "(未指定/自動検出に依存)"
        path_exists = Path(config.MT5_TERMINAL_PATH).exists() if config.MT5_TERMINAL_PATH else None
        if config.MT5_TERMINAL_PATH and not path_exists:
            logger.warning(
                "MT5_PATH='%s' が見つかりません。パスの誤りの可能性があります。",
                config.MT5_TERMINAL_PATH,
            )

        logger.info(
            "MT5データ取得を別プロセスで開始します: symbol=%s timeframe=%s path=%s (存在=%s) "
            "login=%s server=%s timeout=%s秒",
            symbol,
            timeframe,
            path_display,
            path_exists,
            config.MT5_LOGIN or "(未設定)",
            config.MT5_SERVER or "(未設定)",
            timeout_seconds,
        )

        init_kwargs = self._build_init_kwargs(config.MT5_INIT_TIMEOUT_MS)

        ctx = multiprocessing.get_context("spawn")
        result_queue: multiprocessing.Queue = ctx.Queue()
        process = ctx.Process(
            target=_fetch_worker,
            args=(result_queue, init_kwargs, symbol, timeframe, bars_count),
            daemon=True,
        )

        started_at = time.monotonic()
        process.start()

        payload: dict | None = None
        deadline = started_at + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                item = result_queue.get(timeout=min(remaining, _POLL_INTERVAL_SECONDS))
            except queue_module.Empty:
                if not process.is_alive():
                    break
                continue

            if "log" in item:
                level, message = item["log"]
                logger.log(level, message)
                continue

            payload = item.get("result")
            break

        elapsed = time.monotonic() - started_at

        if payload is None:
            if process.is_alive():
                logger.error(
                    "MT5データ取得プロセスが%.1f秒経過しても応答しないため強制終了します(terminate)",
                    elapsed,
                )
                process.terminate()
                process.join(timeout=_TERMINATE_JOIN_TIMEOUT_SECONDS)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=_TERMINATE_JOIN_TIMEOUT_SECONDS)
                raise MT5ConnectionError(
                    f"MT5データ取得がタイムアウトしました({elapsed:.1f}秒応答なし)。"
                    "MT5ターミナルが起動・ログイン済みか、MT5_PATH/MT5_SERVERが正しいか確認してください。"
                )

            process.join(timeout=_TERMINATE_JOIN_TIMEOUT_SECONDS)
            raise MT5ConnectionError(
                f"MT5データ取得プロセスが結果を返さずに終了しました(exitcode={process.exitcode})"
            )

        process.join(timeout=_TERMINATE_JOIN_TIMEOUT_SECONDS)
        if process.is_alive():
            process.terminate()
            process.join(timeout=_TERMINATE_JOIN_TIMEOUT_SECONDS)

        if not payload["ok"]:
            raise MT5ConnectionError(payload["error"])

        logger.info("MT5データ取得に成功しました(%.1f秒)", elapsed)

        tick_data = payload["tick"]
        tick = Tick(
            symbol=tick_data["symbol"],
            bid=tick_data["bid"],
            ask=tick_data["ask"],
            time=datetime.fromtimestamp(tick_data["time"]),
        )

        df = pd.DataFrame(payload["candles"])
        df["time"] = pd.to_datetime(df["time"], unit="s")

        return MarketSnapshot(tick=tick, candles=df)
