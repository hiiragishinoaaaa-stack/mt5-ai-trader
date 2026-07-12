"""発注リクエストの送出(EAブリッジ方式によるPhase2の自動発注)。

実際のMT5への発注(order_send/CTrade.Buy等)はEA側(ea/ARTEMIS_Bridge.mq5)
が行う。このモジュールは、AIの判断(BUY/SELL)を受けて発注リクエストを
JSONファイルへ書き出し、EAが処理した結果(成功/失敗)をファイル経由で
確認するだけで、MT5への直接発注は一切行わない。market_feed.pyと同じ
ファイルブリッジのパターンを踏襲している。

## 安全設計

- `config.DEMO_ONLY` が明示的にTrueでない限り、発注リクエストは一切
  書き出さない(既定でOFF)。
- 実際にデモ口座かどうかの最終確認、既存ポジションの重複チェック、
  発注の実行そのものは全てEA側の責任とする。Python側はMT5の口座状態を
  一切知り得ない(EAブリッジ方式の制約)ため、「Pythonだけを信用しない」
  設計にしている。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass

import config
import discord_notifier
from ai_engine import Signal

logger = logging.getLogger("mt5_ai_trader")

_RESULT_POLL_INTERVAL_SECONDS = 0.5


class OrderExecutionError(RuntimeError):
    """発注リクエストの書き出しに失敗した場合に送出する。"""


@dataclass
class OrderResult:
    """EAが書き出した発注結果。"""

    success: bool
    message: str
    ticket: int | None = None
    retcode: int | None = None


def generate_request_id() -> str:
    """一意な発注リクエストIDを生成する。

    通常運転では毎回このIDを自動生成する。発注テスト用モード
    (main.pyのTEST_ORDER_ONCE)では、呼び出し側がこの関数で1度だけ
    IDを生成し、同じIDをsubmit_if_needed()へ明示的に渡すことで、
    同一テスト実行内での二重発注を防ぐ。
    """
    return f"{int(time.time())}-{uuid.uuid4().hex[:8]}"


class FileOrderExecutor:
    """AIのBUY/SELL判断を受け、発注リクエストJSONを書き出すクラス。"""

    def __init__(self) -> None:
        # 送出済みのrequest_idを覚えておき、同じIDでの再送出(二重発注)を防ぐ。
        self._submitted_request_ids: set[str] = set()

    def submit_if_needed(self, signal: Signal, request_id: str | None = None) -> OrderResult | None:
        """signalがBUY/SELLの場合のみ発注リクエストを送出する。

        WAITの場合は何もしない。DEMO_ONLY=falseの場合も何もしない
        (安全のための既定OFF)。戻り値はEAの処理結果、または
        (送出しなかった/結果を確認できなかった)場合はNone。

        request_idを明示的に渡した場合(発注テスト用モード)、同じIDで
        既に送出済みであれば新たなリクエストは書き出さずスキップする。
        省略した場合(通常のAI判断ループ)は呼び出しのたびに新しいIDを
        自動生成するため、これまで通り毎回発注リクエストを送出できる。
        """
        if signal.action not in ("BUY", "SELL"):
            return None

        if not config.ENABLE_ORDERS:
            logger.info(
                "order_executor: ENABLE_ORDERS=falseのため発注をスキップします"
                "(Dashboard SettingsまたはREADMEを参照し有効化できます)"
            )
            return None

        if not config.DEMO_ONLY:
            logger.info(
                "order_executor: DEMO_ONLY=falseのため発注をスキップします"
                "(.envでDEMO_ONLY=trueにすると有効化されます)"
            )
            return None

        is_test = request_id is not None
        tag = "[TEST MODE] " if is_test else ""
        resolved_request_id = request_id or generate_request_id()

        if resolved_request_id in self._submitted_request_ids:
            logger.warning(
                "order_executor: %srequest_id=%s は送出済みのためスキップします(二重発注防止)",
                tag,
                resolved_request_id,
            )
            return None
        self._submitted_request_ids.add(resolved_request_id)

        request = {
            "request_id": resolved_request_id,
            "created_at": time.time(),
            "action": signal.action,
            "symbol": config.SYMBOL,
            "volume": config.ORDER_VOLUME,
            "sl_points": config.SL_POINTS,
            "tp_points": config.TP_POINTS,
            "demo_only": True,
        }

        self._write_request(request)
        logger.info(
            "order_executor: %s発注リクエストを送出しました request_id=%s action=%s symbol=%s "
            "volume=%s sl_points=%s tp_points=%s",
            tag,
            resolved_request_id,
            signal.action,
            config.SYMBOL,
            config.ORDER_VOLUME,
            config.SL_POINTS,
            config.TP_POINTS,
        )

        result = self._wait_for_result(resolved_request_id)
        if result is None:
            logger.warning(
                "order_executor: %s%s秒待っても結果を確認できませんでした(request_id=%s)。"
                "EAが動作しているか、MT5の「エキスパート」タブを確認してください。",
                tag,
                config.ORDER_RESULT_WAIT_SECONDS,
                resolved_request_id,
            )
            discord_notifier.notify_order_failed(
                signal.action, config.SYMBOL, "EAからの応答がタイムアウトしました(MT5が動作していない可能性があります)"
            )
            return None

        if result.success:
            logger.info(
                "order_executor: %s発注に成功しました request_id=%s ticket=%s message=%s",
                tag,
                resolved_request_id,
                result.ticket,
                result.message,
            )
            discord_notifier.notify_trade_executed(
                signal.action, config.SYMBOL, config.ORDER_VOLUME, result.ticket, result.message
            )
        else:
            logger.error(
                "order_executor: %s発注は実行されませんでした request_id=%s retcode=%s message=%s",
                tag,
                resolved_request_id,
                result.retcode,
                result.message,
            )
            discord_notifier.notify_order_failed(signal.action, config.SYMBOL, result.message)
        return result

    def _write_request(self, request: dict) -> None:
        tmp_path = config.ORDER_REQUEST_FILE_PATH.with_suffix(".tmp")
        try:
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            with tmp_path.open("w", encoding="utf-8") as f:
                # EA側は簡易的な手書きJSONパーサ(区切り文字の間の空白を許容しない
                # 実装だった場合に備え、区切り文字にスペースを入れないコンパクトな
                # 形式で書き出す。json.dump()の既定(", " / ": ")は使わない。
                json.dump(request, f, separators=(",", ":"))
            tmp_path.replace(config.ORDER_REQUEST_FILE_PATH)  # アトミックにリネーム
        except OSError as exc:
            raise OrderExecutionError(f"発注リクエストの書き出しに失敗しました: {exc}") from exc

    def _wait_for_result(self, request_id: str) -> OrderResult | None:
        deadline = time.monotonic() + config.ORDER_RESULT_WAIT_SECONDS
        while True:
            payload = self._try_read_result()
            if payload is not None and payload.get("request_id") == request_id:
                return OrderResult(
                    success=bool(payload.get("success")),
                    message=str(payload.get("message", "")),
                    ticket=payload.get("ticket"),
                    retcode=payload.get("retcode"),
                )
            if time.monotonic() >= deadline:
                return None
            time.sleep(_RESULT_POLL_INTERVAL_SECONDS)

    def _try_read_result(self) -> dict | None:
        path = config.ORDER_RESULT_FILE_PATH
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
