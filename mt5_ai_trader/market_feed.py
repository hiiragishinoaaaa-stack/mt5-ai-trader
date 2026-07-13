"""EAブリッジ方式によるMT5価格データの取得。

MetaTrader5パッケージ(MT5 Python API)は、環境によってmt5.initialize()が
IPC timeoutでハングし続ける問題が解消できなかったため、ARTEMISでは
MT5 Python APIに一切依存しない構成に切り替えている。

代わりに、MT5ターミナル上で動くEA(ea/ARTEMIS_MarketFeed.mq5)が
ティック・ローソク足データを定期的にJSONファイルへ書き出し、Python側は
そのファイルを読むだけにする。ファイルの読み込みはローカルディスクI/Oの
ため、IPC通信のようにハングする心配がなく、mt5_client.pyで実装していた
別プロセス+タイムアウトの仕組みも不要になった。

EAはファイルを一時ファイルに書いてからリネームすることでアトミックに
更新しているため、ここでは万一の読み取りレース(リネーム中に読んでしまう
極めて稀なケース)に備えて簡単なリトライだけ行う。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

import config

logger = logging.getLogger("mt5_ai_trader")

_READ_RETRY_COUNT = 3
_READ_RETRY_DELAY_SECONDS = 0.2

# EAが書き出すローソク足の列(spread/real_volumeは現時点のai_engine/indicators
# では使わないが、将来のDB保存等に備えてそのまま保持しておく)。
_CANDLE_COLUMNS = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]


class MarketFeedError(RuntimeError):
    """EAが書き出したファイルの取得・検証に失敗した場合に送出する。"""


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


class FileMarketFeed:
    """EAが書き出すJSONファイルを読み取り、MarketSnapshotへ変換するクライアント。"""

    def read_snapshot(
        self,
        symbol: str,
        timeframe: str,
        max_staleness_seconds: float | None = None,
    ) -> MarketSnapshot:
        """EAが書き出したJSONファイルを読み、検証した上でMarketSnapshotを返す。

        ファイルが存在しない・壊れている・古すぎる・シンボルが一致しない
        場合はMarketFeedErrorを送出する。
        """
        max_staleness_seconds = (
            max_staleness_seconds
            if max_staleness_seconds is not None
            else config.MARKET_DATA_MAX_STALENESS_SECONDS
        )
        file_path = config.market_data_file_path(symbol)

        if not file_path.exists():
            raise MarketFeedError(
                f"データファイルが見つかりません: {file_path}\n"
                "MT5にARTEMIS_MarketFeed EAを追加し、動作しているか確認してください。"
            )

        payload = self._read_json_with_retry(file_path)

        payload_symbol = payload.get("symbol")
        if payload_symbol != symbol:
            raise MarketFeedError(
                f"EAが書き出したシンボル('{payload_symbol}')が期待値('{symbol}')と一致しません。"
                "EAのInpSymbolと.envのSYMBOLを揃えてください。"
            )

        updated_at = payload.get("updated_at")
        if updated_at is None:
            raise MarketFeedError("データファイルにupdated_atがありません(壊れている可能性があります)")
        updated_at = config.correct_ea_timestamp(float(updated_at))

        age_seconds = time.time() - updated_at
        if age_seconds > max_staleness_seconds:
            raise MarketFeedError(
                f"データが古すぎます(最終更新から{age_seconds:.0f}秒経過、"
                f"許容={max_staleness_seconds}秒)。MT5でEAが動作しているか確認してください。"
            )

        logger.debug(
            "market_feed: symbol=%s timeframe(EA)=%s age=%.1f秒 のデータを読み込みました",
            payload_symbol,
            payload.get("timeframe"),
            age_seconds,
        )

        tick_data = payload.get("tick")
        candles_data = payload.get("candles")
        if not tick_data or not candles_data:
            raise MarketFeedError("データファイルにtickまたはcandlesがありません(壊れている可能性があります)")

        tick = Tick(
            symbol=symbol,
            bid=float(tick_data["bid"]),
            ask=float(tick_data["ask"]),
            time=datetime.fromtimestamp(config.correct_ea_timestamp(float(tick_data["time"]))),
        )

        df = pd.DataFrame(candles_data, columns=_CANDLE_COLUMNS)
        df["time"] = df["time"].apply(config.correct_ea_timestamp)
        df["time"] = pd.to_datetime(df["time"], unit="s")

        return MarketSnapshot(tick=tick, candles=df)

    def _read_json_with_retry(self, file_path: Path) -> dict:
        last_error: Exception | None = None
        for attempt in range(1, _READ_RETRY_COUNT + 1):
            try:
                with file_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                last_error = exc
                logger.debug(
                    "market_feed: ファイル読み込みに失敗(試行%s/%s): %s",
                    attempt,
                    _READ_RETRY_COUNT,
                    exc,
                )
                time.sleep(_READ_RETRY_DELAY_SECONDS)

        raise MarketFeedError(
            f"データファイルの読み込みに失敗しました: {file_path} ({last_error})"
        )
