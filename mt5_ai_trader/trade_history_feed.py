"""EAブリッジ方式によるMT5の取引履歴(決済済みポジション)の取得。

market_feed.py/account_feed.pyと同じ考え方で、MT5ターミナル上で動くEA
(ea/ARTEMIS_Bridge.mq5)が最近決済されたポジション一覧を定期的にJSON
ファイルへ書き出し、Python側はそのファイルを読むだけにする。Dashboardの
Trade/Home/Analytics画面はsettings_server.py経由でこのモジュールを使う。

このファイルには「なぜAIがそう判断したか」という理由は含まれない
(MT5は発注理由を知らないため)。判断理由が必要な場合はai_status.pyの
直近の判断を参照する。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import config

logger = logging.getLogger("mt5_ai_trader")

_READ_RETRY_COUNT = 3
_READ_RETRY_DELAY_SECONDS = 0.2


class TradeHistoryError(RuntimeError):
    """EAが書き出したファイルの取得・検証に失敗した場合に送出する。"""


@dataclass
class ClosedTrade:
    position_id: int
    symbol: str
    type: str  # "BUY" or "SELL"
    volume: float
    price_open: float
    price_close: float
    profit: float
    open_time: int
    close_time: int
    magic: int
    is_artemis: bool


class FileTradeHistoryFeed:
    """EAが書き出すJSONファイルを読み取り、ClosedTradeのリストへ変換するクライアント。"""

    def read_history(self, max_staleness_seconds: float | None = None) -> list[ClosedTrade]:
        """EAが書き出したJSONファイルを読み、検証した上で決済済み取引の一覧を返す。

        新しい順(close_timeの降順)に並べ替えて返す。
        ファイルが存在しない・壊れている・古すぎる場合はTradeHistoryErrorを送出する。
        """
        max_staleness_seconds = (
            max_staleness_seconds
            if max_staleness_seconds is not None
            else config.TRADE_HISTORY_MAX_STALENESS_SECONDS
        )
        file_path = config.TRADE_HISTORY_FILE_PATH

        if not file_path.exists():
            raise TradeHistoryError(
                f"取引履歴ファイルが見つかりません: {file_path}\n"
                "MT5にARTEMIS_Bridge EA(v4.00以降)を追加し、動作しているか確認してください。"
            )

        payload = self._read_json_with_retry(file_path)

        updated_at = payload.get("updated_at")
        if updated_at is None:
            raise TradeHistoryError("取引履歴ファイルにupdated_atがありません(壊れている可能性があります)")

        age_seconds = time.time() - float(updated_at)
        if age_seconds > max_staleness_seconds:
            raise TradeHistoryError(
                f"取引履歴が古すぎます(最終更新から{age_seconds:.0f}秒経過、"
                f"許容={max_staleness_seconds}秒)。MT5でEAが動作しているか確認してください。"
            )

        trades_data = payload.get("trades")
        if trades_data is None:
            raise TradeHistoryError("取引履歴ファイルにtradesがありません(壊れている可能性があります)")

        trades = [
            ClosedTrade(
                position_id=int(t["position_id"]),
                symbol=str(t["symbol"]),
                type=str(t["type"]),
                volume=float(t["volume"]),
                price_open=float(t["price_open"]),
                price_close=float(t["price_close"]),
                profit=float(t["profit"]),
                open_time=int(t["open_time"]),
                close_time=int(t["close_time"]),
                magic=int(t["magic"]),
                is_artemis=bool(t["is_artemis"]),
            )
            for t in trades_data
        ]
        trades.sort(key=lambda t: t.close_time, reverse=True)

        logger.debug(
            "trade_history_feed: %d件の取引履歴を読み込みました(age=%.1f秒)",
            len(trades),
            age_seconds,
        )

        return trades

    def _read_json_with_retry(self, file_path: Path) -> dict:
        last_error: Exception | None = None
        for attempt in range(1, _READ_RETRY_COUNT + 1):
            try:
                with file_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                last_error = exc
                logger.debug(
                    "trade_history_feed: ファイル読み込みに失敗(試行%s/%s): %s",
                    attempt,
                    _READ_RETRY_COUNT,
                    exc,
                )
                time.sleep(_READ_RETRY_DELAY_SECONDS)

        raise TradeHistoryError(
            f"取引履歴ファイルの読み込みに失敗しました: {file_path} ({last_error})"
        )
