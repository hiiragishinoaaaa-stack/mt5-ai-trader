"""手動決済リクエストの送出(Phase 10: DashboardのCLOSEボタン)。

EAブリッジ方式で、order_executor.pyと同じファイルブリッジのパターンを
踏襲する(別ファイルを使うのは、main.pyのAI判断ループが送出する通常の
発注リクエストと、Dashboardからの手動決済リクエストが同時に発生しても
ファイルが衝突しないようにするため)。

実際のポジション決済(CTrade.PositionClose)はEA側(ea/ARTEMIS_Bridge.mq5、
v4.03以降)が行う。このモジュールはリクエストをJSONファイルへ書き出し、
EAが処理した結果をファイル経由で確認するだけ。

## 安全設計

- `config.DEMO_ONLY` が明示的にTrueでない限り、決済リクエストは一切
  書き出さない(発注と同じ既定OFFの安全設計)。
- `config.ENABLE_ORDERS` が明示的にTrueでない限り、決済リクエストは
  一切書き出さない(EA側の`InpEnableOrders`がfalseの場合も同様に
  `g_orders_effectively_enabled`でブロックされるため、二重にガードされる)。
- 実際にデモ口座かどうかの最終確認、対象ポジションの特定・決済の実行
  そのものは全てEA側の責任とする。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass

import config

logger = logging.getLogger("mt5_ai_trader")

_RESULT_POLL_INTERVAL_SECONDS = 0.5


class PositionCloseError(RuntimeError):
    """決済リクエストの書き出しに失敗した場合に送出する。"""


@dataclass
class CloseResult:
    """EAが書き出した決済結果。"""

    success: bool
    message: str
    closed_count: int = 0


class FilePositionCloser:
    """DashboardのCLOSEボタンを受け、決済リクエストJSONを書き出すクラス。"""

    def close_all(self, symbol: str) -> CloseResult:
        """指定した銘柄の、ARTEMIS自身が保有する全ポジションの決済を要求する。

        symbolは複数銘柄対応(Phase 12)により呼び出し元(settings_server.py)から
        明示的に渡される。config.ENABLED_SYMBOLSに含まれる銘柄ごとに別々の
        リクエスト/結果ファイル(config.close_request_file_path()等)を使うため、
        この引数で対象銘柄を特定する。

        戻り値はEAの処理結果。DEMO_ONLY/ENABLE_ORDERSが有効でない場合や、
        EAからの応答がタイムアウトした場合はCloseResult(success=False, ...)を返す
        (例外は送出しない。呼び出し元のHTTPハンドラがそのままレスポンスに使える)。
        """
        if not config.ENABLE_ORDERS:
            return CloseResult(
                success=False,
                message="ENABLE_ORDERS=falseのため決済できません(Dashboard Settingsで有効化してください)",
            )

        if not config.DEMO_ONLY:
            return CloseResult(
                success=False,
                message="DEMO_ONLY=falseのため決済できません(.envでDEMO_ONLY=trueにすると有効化されます)",
            )

        request_id = f"close-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        request = {
            "request_id": request_id,
            "created_at": time.time(),
            "symbol": symbol,
            "demo_only": True,
        }

        try:
            self._write_request(request, symbol)
        except PositionCloseError as exc:
            logger.error("position_closer: 決済リクエストの書き出しに失敗しました: %s", exc)
            return CloseResult(success=False, message=str(exc))

        logger.info("position_closer: 決済リクエストを送出しました request_id=%s symbol=%s", request_id, symbol)

        result = self._wait_for_result(request_id, symbol)
        if result is None:
            logger.warning(
                "position_closer: %s秒待っても結果を確認できませんでした(request_id=%s)。"
                "EAが動作しているか、MT5の「エキスパート」タブを確認してください。",
                config.ORDER_RESULT_WAIT_SECONDS,
                request_id,
            )
            return CloseResult(success=False, message="EAからの応答がタイムアウトしました(MT5が動作していない可能性があります)")

        if result.success:
            logger.info("position_closer: 決済に成功しました request_id=%s message=%s", request_id, result.message)
        else:
            logger.error("position_closer: 決済に失敗しました request_id=%s message=%s", request_id, result.message)
        return result

    def _write_request(self, request: dict, symbol: str) -> None:
        request_path = config.close_request_file_path(symbol)
        tmp_path = request_path.with_suffix(".tmp")
        try:
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(request, f, separators=(",", ":"))
            tmp_path.replace(request_path)
        except OSError as exc:
            raise PositionCloseError(f"決済リクエストの書き出しに失敗しました: {exc}") from exc

    def _wait_for_result(self, request_id: str, symbol: str) -> CloseResult | None:
        deadline = time.monotonic() + config.ORDER_RESULT_WAIT_SECONDS
        while True:
            payload = self._try_read_result(symbol)
            if payload is not None and payload.get("request_id") == request_id:
                return CloseResult(
                    success=bool(payload.get("success")),
                    message=str(payload.get("message", "")),
                    closed_count=int(payload.get("closed_count", 0)),
                )
            if time.monotonic() >= deadline:
                return None
            time.sleep(_RESULT_POLL_INTERVAL_SECONDS)

    def _try_read_result(self, symbol: str) -> dict | None:
        path = config.close_result_file_path(symbol)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
