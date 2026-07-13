"""EAブリッジ方式によるMT5口座情報(残高・証拠金・保有ポジション)の取得。

market_feed.pyと同じ考え方で、MT5ターミナル上で動くEA
(ea/ARTEMIS_Bridge.mq5)が口座情報・ポジション一覧を定期的にJSONファイルへ
書き出し、Python側はそのファイルを読むだけにする。Dashboardの
Home/Trade画面はsettings_server.py経由でこのモジュールを使う。
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


class AccountFeedError(RuntimeError):
    """EAが書き出したファイルの取得・検証に失敗した場合に送出する。"""


@dataclass
class AccountInfo:
    login: int
    currency: str
    balance: float
    equity: float
    margin: float
    margin_free: float
    profit: float


@dataclass
class Position:
    ticket: int
    symbol: str
    type: str  # "BUY" or "SELL"
    volume: float
    price_open: float
    price_current: float
    sl: float
    tp: float
    profit: float
    open_time: int
    magic: int
    is_artemis: bool


@dataclass
class AccountState:
    account: AccountInfo
    positions: list[Position]
    # EAが最後にこのファイルを書いた時刻(補正済み、config.correct_ea_timestamp
    # 適用後)。risk_manager.pyが「今」の基準として使う場合がある(EA由来の
    # open_time/close_timeと同じ時計・同じ補正定数で比較することで、補正定数
    # 自体の精度に依存せず経過時間を正しく計算できるようにするため。詳細は
    # risk_manager.check_entry_allowed()参照)。既定0.0は後方互換用
    # (テストや古い呼び出し元がこの引数を渡さない場合)。
    updated_at: float = 0.0


class FileAccountFeed:
    """EAが書き出すJSONファイルを読み取り、AccountStateへ変換するクライアント。"""

    def read_state(self, max_staleness_seconds: float | None = None) -> AccountState:
        """EAが書き出したJSONファイルを読み、検証した上でAccountStateを返す。

        ファイルが存在しない・壊れている・古すぎる場合はAccountFeedErrorを送出する。
        """
        max_staleness_seconds = (
            max_staleness_seconds
            if max_staleness_seconds is not None
            else config.ACCOUNT_STATE_MAX_STALENESS_SECONDS
        )
        file_path = config.ACCOUNT_STATE_FILE_PATH

        if not file_path.exists():
            raise AccountFeedError(
                f"口座情報ファイルが見つかりません: {file_path}\n"
                "MT5にARTEMIS_Bridge EAを追加し、動作しているか確認してください。"
            )

        payload = self._read_json_with_retry(file_path)

        updated_at = payload.get("updated_at")
        if updated_at is None:
            raise AccountFeedError("口座情報ファイルにupdated_atがありません(壊れている可能性があります)")
        updated_at = config.correct_ea_timestamp(float(updated_at))

        age_seconds = time.time() - updated_at
        if age_seconds > max_staleness_seconds:
            raise AccountFeedError(
                f"口座情報が古すぎます(最終更新から{age_seconds:.0f}秒経過、"
                f"許容={max_staleness_seconds}秒)。MT5でEAが動作しているか確認してください。"
            )

        account_data = payload.get("account")
        positions_data = payload.get("positions")
        if account_data is None or positions_data is None:
            raise AccountFeedError("口座情報ファイルにaccountまたはpositionsがありません(壊れている可能性があります)")

        account = AccountInfo(
            login=int(account_data["login"]),
            currency=str(account_data["currency"]),
            balance=float(account_data["balance"]),
            equity=float(account_data["equity"]),
            margin=float(account_data["margin"]),
            margin_free=float(account_data["margin_free"]),
            profit=float(account_data["profit"]),
        )

        positions = [
            Position(
                ticket=int(p["ticket"]),
                symbol=str(p["symbol"]),
                type=str(p["type"]),
                volume=float(p["volume"]),
                price_open=float(p["price_open"]),
                price_current=float(p["price_current"]),
                sl=float(p["sl"]),
                tp=float(p["tp"]),
                profit=float(p["profit"]),
                open_time=config.correct_ea_timestamp(p["open_time"]),
                magic=int(p["magic"]),
                is_artemis=bool(p["is_artemis"]),
            )
            for p in positions_data
        ]

        logger.debug(
            "account_feed: balance=%s equity=%s positions=%d件 age=%.1f秒 のデータを読み込みました",
            account.balance,
            account.equity,
            len(positions),
            age_seconds,
        )

        return AccountState(account=account, positions=positions, updated_at=updated_at)

    def _read_json_with_retry(self, file_path: Path) -> dict:
        last_error: Exception | None = None
        for attempt in range(1, _READ_RETRY_COUNT + 1):
            try:
                with file_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                last_error = exc
                logger.debug(
                    "account_feed: ファイル読み込みに失敗(試行%s/%s): %s",
                    attempt,
                    _READ_RETRY_COUNT,
                    exc,
                )
                time.sleep(_READ_RETRY_DELAY_SECONDS)

        raise AccountFeedError(
            f"口座情報ファイルの読み込みに失敗しました: {file_path} ({last_error})"
        )
